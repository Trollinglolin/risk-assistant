# Independent R implementation used to cross-check the Python engine.
# NOTE: a stand-in, not the RMSC4002 coursework. Replace / extend it with the RMSC4002
# coursework scripts and keep the same output format (metric,value).
#
#   Rscript reference/validate_reference.R      (run from the repo root)
suppressPackageStartupMessages({ library(rugarch); library(evir) })

x     <- read.csv("reference/input.csv")
value <- as.numeric(readLines("reference/value.txt"))
L     <- -x$pnl
a     <- 0.99
out   <- list()

# historical (quantile type 7 == numpy 'linear')
out$hist_var <- quantile(L, a, type = 7, names = FALSE)
out$hist_es  <- mean(L[L >= out$hist_var])

# normal
mu <- mean(L); s <- sd(L)
out$normal_var <- mu + s * qnorm(a)
out$normal_es  <- mu + s * dnorm(qnorm(a)) / (1 - a)

# Student-t with fixed nu = 5, scale matched to sd
nu <- 5; sc <- s * sqrt((nu - 2) / nu); q <- qt(a, nu)
out$t5_var <- mu + sc * q
out$t5_es  <- mu + sc * dt(q, nu) / (1 - a) * (nu + q^2) / (nu - 1)

# GARCH(1,1), constant mean, Student-t innovations, returns in percent
spec <- ugarchspec(variance.model = list(model = "sGARCH", garchOrder = c(1, 1)),
                   mean.model = list(armaOrder = c(0, 0), include.mean = TRUE),
                   distribution.model = "std")
fit <- ugarchfit(spec, x$ret * 100, solver = "hybrid")
cf  <- coef(fit)
out$garch_mu <- cf["mu"]; out$garch_omega <- cf["omega"]
out$garch_alpha <- cf["alpha1"]; out$garch_beta <- cf["beta1"]; out$garch_nu <- cf["shape"]

# EVT: GPD by ML on excesses over the 95% quantile (type 7 threshold)
u   <- quantile(L, 0.95, type = 7, names = FALSE)
g   <- gpd(L, threshold = u, method = "ml")
xi  <- g$par.ests["xi"]; be <- g$par.ests["beta"]; nu_ <- g$n.exceed; n <- length(L)
out$evt_xi   <- xi; out$evt_beta <- be
out$evt_var  <- u + be / xi * (((n / nu_) * (1 - a))^(-xi) - 1)

# Kupiec POF on the Python historical backtest exceptions
e <- read.csv("reference/exceptions.csv")$exception
T <- length(e); k <- sum(e); p <- 1 - a; ph <- k / T
out$kupiec_lr <- -2 * ((T - k) * log(1 - p) + k * log(p)) + 2 * ((T - k) * log(1 - ph) + k * log(ph))

res <- data.frame(metric = names(out), value = sprintf("%.15g", unlist(out)))
write.csv(res, "reference/r_results.csv", row.names = FALSE, quote = FALSE)
print(res)
