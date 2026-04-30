import requests

def test_download():
    url = "http://127.0.0.1:5000/api/download-template"
    try:
        res = requests.get(url)
        print(f"Status Code: {res.status_code}")
        print(f"Headers: {res.headers}")
        if res.status_code == 200:
            if 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' in res.headers.get('Content-Type', ''):
                print("SUCCESS: Content-Type is correct (Excel).")
                with open('test_download.xlsx', 'wb') as f:
                    f.write(res.content)
                print("Saved to test_download.xlsx")
            else:
                print(f"FAILURE: Wrong Content-Type: {res.headers.get('Content-Type')}")
        else:
            print(f"FAILURE: Server returned {res.status_code}")
            print(res.text)
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_download()
