from app.utils.proxy import detect_scheme, parse_proxy_blob, parse_proxy_file, parse_proxy_line


def test_detect_scheme_aliases():
    assert detect_scheme("SOCKS") == "socks5"
    assert detect_scheme("socks4a") == "socks4"
    assert detect_scheme("https") == "https"
    assert detect_scheme("ssl") == "https"
    assert detect_scheme("HTTP") == "http"
    assert detect_scheme("s5") == "socks5"


def test_urls():
    s5 = parse_proxy_line("socks5://u:p@10.0.0.1:9050")
    assert s5 and s5.scheme == "socks5" and s5.username == "u" and s5.explicit
    http = parse_proxy_line("http://10.0.0.1:8080")
    assert http and http.scheme == "http" and http.port == 8080 and http.explicit
    https = parse_proxy_line("https://user:pass@10.0.0.1:443")
    assert https and https.scheme == "https" and https.password == "pass" and https.explicit
    s4 = parse_proxy_line("socks4://10.0.0.1:4145")
    assert s4 and s4.scheme == "socks4"


def test_port_guess_without_scheme():
    assert parse_proxy_line("1.2.3.4:1080").scheme == "socks5"
    assert parse_proxy_line("1.2.3.4:8080").scheme == "http"
    assert parse_proxy_line("1.2.3.4:443").scheme == "https"
    assert parse_proxy_line("1.2.3.4:3128").scheme == "http"
    assert parse_proxy_line("1.2.3.4:9050").scheme == "socks5"


def test_trailing_and_leading_type():
    a = parse_proxy_line("10.0.0.1:9050:user:pass:socks5")
    assert a and a.scheme == "socks5" and a.username == "user" and a.password == "pass"
    b = parse_proxy_line("10.0.0.1:8080:user:pass:http")
    assert b and b.scheme == "http" and b.password == "pass"
    c = parse_proxy_line("https:10.0.0.1:443:user:secret")
    assert c and c.scheme == "https" and c.password == "secret"
    d = parse_proxy_line("socks5 10.0.0.1 1080 user pass")
    assert d and d.scheme == "socks5" and d.port == 1080 and d.username == "user"


def test_auth_forms():
    a = parse_proxy_line("user:pass@10.0.0.1:9050")
    assert a and a.username == "user" and a.host == "10.0.0.1"
    b = parse_proxy_line("10.0.0.1:9050@user:pass")
    assert b and b.username == "user" and b.password == "pass"
    c = parse_proxy_line("10.0.0.1:9050:user:pass")
    assert c and c.username == "user" and c.password == "pass"


def test_csv_and_semicolon():
    blob = parse_proxy_blob(
        "http,1.1.1.1,8080,u,p\nsocks5;2.2.2.2;1080;u;p\n# skip\n"
    )
    schemes = {item.scheme for item in blob}
    assert "http" in schemes
    assert "socks5" in schemes
    assert len(blob) == 2


def test_https_not_collapsed_to_http():
    item = parse_proxy_line("https://10.0.0.1:8443")
    assert item and item.scheme == "https"


def test_file_csv_header():
    raw = "type,host,port,user,pass\nhttps,8.8.8.8,443,login,secret\n".encode()
    items = parse_proxy_file(raw, "proxies.csv")
    assert len(items) == 1
    assert items[0].scheme == "https"
    assert items[0].username == "login"
    assert items[0].password == "secret"
