# AWS deploy (Step 15), serverless path

```
Docker build ──► ECR ──► Lambda "hkrisk-api"    (Function URL → FastAPI via Lambda Web Adapter)
                     └─► Lambda "hkrisk-report" (EventBridge Scheduler, Mon–Fri 18:30 Asia/Hong_Kong → S3)
```

**Do these first:** create an AWS Budgets alert (e.g. USD 10), and check the current
free-tier terms (they changed in 2025). Nothing below has been run yet.

```bash
export AWS_REGION=ap-east-1 ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export BUCKET=hkrisk-$ACCOUNT REPO=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

# 0. budget alert (edit email)
aws budgets create-budget --account-id $ACCOUNT --budget '{"BudgetName":"hkrisk","BudgetLimit":{"Amount":"10","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]}]'

# 1. bucket + secrets (SSM SecureString; never in the image)
aws s3 mb s3://$BUCKET
# parameter names = the env var they fill; loaded at cold start (HKRISK_SSM_PREFIX), so secrets
# never sit in the image or the Lambda environment configuration
aws ssm put-parameter --name /hkrisk/GEMINI_API_KEY --type SecureString --value "<your key>"
aws ssm put-parameter --name /hkrisk/HKRISK_API_KEY --type SecureString \
  --value "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# 2. images
aws ecr create-repository --repository-name hkrisk
aws ecr get-login-password | docker login --username AWS --password-stdin $REPO
docker build --platform linux/arm64 --provenance=false --target api    -t $REPO/hkrisk:api .
docker build --platform linux/arm64 --provenance=false --target report -t $REPO/hkrisk:report .
docker push $REPO/hkrisk:api && docker push $REPO/hkrisk:report

# 3. IAM role (least privilege): see infra/policy.json; trust lambda.amazonaws.com
aws iam create-role --role-name hkrisk-lambda --assume-role-policy-document file://infra/trust.json
aws iam put-role-policy --role-name hkrisk-lambda --policy-name hkrisk --policy-document file://infra/policy.json
aws iam attach-role-policy --role-name hkrisk-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# 4. functions: 120 s timeout, 2 GB memory (scipy/arch need CPU), arm64
aws lambda create-function --function-name hkrisk-api --package-type Image --architectures arm64 \
  --code ImageUri=$REPO/hkrisk:api --role arn:aws:iam::$ACCOUNT:role/hkrisk-lambda \
  --timeout 120 --memory-size 2048 \
  --environment "Variables={HKRISK_SSM_PREFIX=/hkrisk,HKRISK_PRICES=s3://$BUCKET/data/prices_live.parquet,LLM_PROVIDER=gemini,LLM_RPM=15,LLM_RPD=500,HKRISK_CORS_ORIGINS=https://<dashboard-domain>}"
# cap cost and abuse: at most 5 concurrent API instances (the in-memory rate limits are per instance)
aws lambda put-function-concurrency --function-name hkrisk-api --reserved-concurrent-executions 5
aws lambda create-function-url-config --function-name hkrisk-api --auth-type NONE
aws lambda add-permission --function-name hkrisk-api --statement-id url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE

aws lambda create-function --function-name hkrisk-report --package-type Image --architectures arm64 \
  --code ImageUri=$REPO/hkrisk:report --role arn:aws:iam::$ACCOUNT:role/hkrisk-lambda \
  --timeout 300 --memory-size 2048 --environment "Variables={REPORT_BUCKET=$BUCKET}"

# 5. schedule: weekdays 18:30 Hong Kong time (HK cash close 16:00)
aws scheduler create-schedule --name hkrisk-daily --schedule-expression "cron(30 18 ? * MON-FRI *)" \
  --schedule-expression-timezone Asia/Hong_Kong --flexible-time-window Mode=OFF \
  --target "{\"Arn\":\"arn:aws:lambda:$AWS_REGION:$ACCOUNT:function:hkrisk-report\",\"RoleArn\":\"arn:aws:iam::$ACCOUNT:role/hkrisk-scheduler\"}"
```

**Secrets at runtime:** with `HKRISK_SSM_PREFIX=/hkrisk` the API reads `/hkrisk/<ENV_NAME>`
SecureStrings at cold start (`src/hkrisk/ssm.py`, allow-listed names only). Rotate the agent key
by setting `/hkrisk/HKRISK_API_KEYS` to `old,new`, moving clients over, then dropping `old`.

**Security checklist** (details in `SECURITY.md`):
- [ ] Budget alert set before anything else
- [ ] Secrets only in SSM; `HKRISK_API_KEY` is >= 24 random characters (weaker keys disable the agent)
- [ ] Reserved concurrency on `hkrisk-api`; `HKRISK_IP_RATE_LIMIT_PER_MIN` / `HKRISK_RATE_LIMIT_PER_MIN` reviewed
- [ ] `HKRISK_CORS_ORIGINS` set to the dashboard origin only (never `*`)
- [ ] `/docs` stays off in the image (`HKRISK_DOCS=0`); turn on only for a demo
- [ ] Dashboard on S3 is private behind CloudFront (Origin Access Control), with a response-headers
      policy: HSTS, `X-Content-Type-Options: nosniff`, `frame-ancestors 'none'` and a CSP such as
      `default-src 'self'; connect-src 'self' https://<api-url>; img-src 'self' data:; style-src 'self' 'unsafe-inline'`
      (the inline theme script needs its sha256 hash in `script-src`)
- [ ] CloudWatch log retention set (e.g. 30 days); alarm on 401/429 spikes in the `hkrisk.audit` log

**Checks (Done when):**
- `curl $URL/risk/var` returns JSON from your phone
- `curl -X POST $URL/agent/ask -d '{"question":"VaR?"}' -H 'content-type: application/json'` → 401
- `reports/<date>/report.html` appears in S3 each weekday; holidays are skipped (`status: skipped`)

The scheduler needs its own role `hkrisk-scheduler` allowed to `lambda:InvokeFunction` on `hkrisk-report`.
