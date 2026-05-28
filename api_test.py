import urllib.request

url = "https://git.eurun.eu.org"
token = "00bc6ae599e1e40be5187273dac1a83d19456bb7"


def test_get_org():
    req = urllib.request.Request(f"{url}/api/v1/orgs/HKTSE_s.r.o")
    req.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            print("GET org: Status", resp.status)
    except Exception as e:
        print("GET org Error:", e)


def test_mirror_sync():
    req = urllib.request.Request(
        f"{url}/api/v1/repos/yuanweize/AWS-Panel/mirror-sync", method="POST"
    )
    req.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            print("POST mirror-sync: Status", resp.status)
    except Exception as e:
        print("POST mirror-sync Error:", e)


test_get_org()
test_mirror_sync()
