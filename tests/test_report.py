from hkrisk.report import build_report


def test_build_report_offline(small_prices, snapshot, holdings):
    report, html = build_report(snapshot, holdings)
    assert report["as_of"] == "2026-10-30" and not report["stale"]
    assert set(report["stress"]) == {"gfc_2008", "covid_2020", "china_tech_2022"}
    assert len(report["top5_es_contributors"]) == 5
    assert report["traffic_light_250d"]["zone"] in {"green", "yellow", "red"}
    assert "<html>" in html and "STALE" not in html.split("<body>")[1].split("<h2>")[0]
