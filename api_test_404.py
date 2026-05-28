import urllib.request, json

url = "https://git.eurun.eu.org"
token = "00bc6ae599e1e40be5187273dac1a83d19456bb7"


def test_get_org_404():
    req = urllib.request.Request(f"{url}/api/v1/orgs/NonExistentOrg12345")
    req.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            print("GET org: Status", resp.status)
    except urllib.error.HTTPError as e:
        print("GET org Error:", e.code)


test_get_org_404()
