from app.ai.brain import between_messages, typing_seconds
from app.ai.contacts import classify_line, classify_token, parse_contacts_file, parse_lines
from app.utils.proxy import parse_proxy_blob, parse_proxy_line


def test_username_at():
    got = classify_line("@durov")
    assert got and got.kind == "username" and got.value == "durov"


def test_tme_link():
    got = classify_line("https://t.me/durov")
    assert got and got.kind == "username" and got.value == "durov"


def test_phone_plus():
    got = classify_line(" +7 999 123-45-67 ")
    assert got and got.kind == "phone"
    assert got.value.startswith("+7")


def test_user_id_not_phone():
    got = classify_line("123456789")
    assert got and got.kind == "user_id"
    assert got.value == "123456789"


def test_md_and_bullets():
    parsed = parse_lines("- @durov\n* [two](https://t.me/telegram)\n# comment\n")
    values = {c.value for c in parsed.contacts}
    assert values == {"durov", "telegram"}


def test_plain_name_skipped():
    assert classify_line("Александр") is None
    assert classify_line("Hello") is None


def test_csv_header(tmp_path):
    raw = "username,phone\n@alpha_user,\n,+79990001122\n".encode()
    parsed = parse_contacts_file(raw, "base.csv")
    kinds = {c.kind for c in parsed.contacts}
    assert "username" in kinds
    assert "phone" in kinds


def test_proxy_formats():
    a = parse_proxy_line("1.2.3.4:1080")
    assert a and a.host == "1.2.3.4" and a.port == 1080
    b = parse_proxy_line("socks5://u:p@10.0.0.1:9050")
    assert b and b.username == "u" and b.password == "p" and b.scheme == "socks5"
    c = parse_proxy_line("10.0.0.1:9050:user:pass")
    assert c and c.username == "user" and c.password == "pass"
    d = parse_proxy_line("user:pass@10.0.0.1:9050")
    assert d and d.host == "10.0.0.1"
    blob = parse_proxy_blob("1.2.3.4:1080\n1.2.3.4:1080\n# skip\n")
    assert len(blob) == 1
    http = parse_proxy_line("http://10.0.0.1:8080")
    assert http and http.scheme == "http"


def test_human_bounds():
    t = typing_seconds("привет, это тестовое сообщение " * 4)
    assert 1.15 <= t <= 9.4
    d = between_messages(40, 90)
    assert 40 <= d <= 90
