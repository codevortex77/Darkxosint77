from flask import Flask, request, jsonify
import requests
import re
import time
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import random

app = Flask(__name__)

EXPIRY_DATE = datetime.now() + timedelta(days=31)

SMC_HOMEPAGE = "https://www.smcinsurance.com/"
SMC_API = "https://www.smcinsurance.com/central/centralcall/CallReqWithHeader"

HOMEPAGE_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml?statecd=Mzc2MzM2MzAzNjY0MzIzODM3NjIzNjY0MzY2MjM3NDQ0Yw=="
HOMEPAGE_BASE = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml"
LOGIN_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/usermgmt/login.xhtml"
FORM_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/balanceservice/form_reschedule_fitness.xhtml"

# Free Indian proxies - try multiple
INDIAN_PROXIES = [
    None,  # Try without proxy first
    "103.149.162.194:8080",
    "43.255.113.232:8080",
    "103.141.140.250:8080",
    "103.141.140.254:8080",
    "103.155.54.26:8080",
    "103.149.162.194:80",
    "103.141.140.250:80",
]

def get_random_proxy():
    """Get random Indian proxy"""
    proxy_ip = random.choice(INDIAN_PROXIES)
    if proxy_ip is None:
        return None
    return {
        'http': f'http://{proxy_ip}',
        'https': f'http://{proxy_ip}'
    }

def create_session(use_proxy=True):
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    
    if use_proxy:
        proxy = get_random_proxy()
        if proxy:
            session.proxies.update(proxy)
            print(f"Using proxy: {proxy}")
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    return session

def get_vehicle_details_from_smc(vehicle_number):
    # Try multiple proxies for SMC
    for attempt in range(3):
        try:
            proxy = get_random_proxy() if attempt > 0 else None
            with requests.Session() as s:
                if proxy:
                    s.proxies.update(proxy)
                
                home = s.get(SMC_HOMEPAGE, timeout=30)
                home.raise_for_status()

                mcbc_cookie = s.cookies.get("MCBC")
                if not mcbc_cookie:
                    continue

                payload = {
                    "url": "GetVaahanDetailsByVehicleNo",
                    "props": [vehicle_number, "", "0"]
                }

                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "okhttp/4.9.2",
                    "Cookie": f"MCBC={mcbc_cookie}"
                }

                response = s.post(SMC_API, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()

                if data.get("statusCode") == 200:
                    vehicle_data = data.get("response", {})
                    chassis = vehicle_data.get("chassis", "").replace(" ", "")
                    mobile_no = vehicle_data.get("mobile_no", "")

                    if len(chassis) >= 5:
                        return {
                            "success": True,
                            "chassis_last_5": chassis[-5:],
                            "mobile_no": mobile_no,
                            "vehicle_data": vehicle_data
                        }
                    return {"success": False, "error": "Chassis too short"}
                return {"success": False, "error": "No data from SMC"}
        except Exception as e:
            print(f"SMC attempt {attempt+1} failed: {e}")
            continue
    
    return {"success": False, "error": "SMC API unavailable"}

def extract_viewstate(html):
    soup = BeautifulSoup(html, 'html.parser')
    vs = soup.find('input', {'name': 'javax.faces.ViewState'})
    return vs.get('value') if vs else None

def extract_viewstate_from_ajax(text):
    m = re.search(r'<update id="j_id1:javax.faces.ViewState:0"><!\[CDATA\[(.*?)\]\]></update>', text)
    return m.group(1) if m else None

def find_checkbox_id(html):
    m = re.search(r'<div[^>]*id="(j_idt\d+)"[^>]*class="[^"]*ui-chkbox', html)
    if not m:
        m = re.search(r'PrimeFaces.cw\("SelectBooleanCheckbox"[^}]*id:"(j_idt\d+)"', html)
    return m.group(1) if m else "j_idt193"

def fetch_mobile_number(vehicle_number, chassis_last_5, fallback_mobile=""):
    # Try Vahan with multiple proxies
    for proxy_attempt in range(3):
        session = create_session(use_proxy=(proxy_attempt > 0))
        
        ajax_headers = {
            'Accept': 'application/xml, text/xml, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Faces-Request': 'partial/ajax',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://vahan.parivahan.gov.in',
        }

        for attempt in range(2):
            try:
                print(f"Vahan attempt {attempt+1} with proxy #{proxy_attempt}")
                
                r1 = session.get(HOMEPAGE_URL, timeout=45)
                if r1.status_code != 200:
                    continue
                viewstate = extract_viewstate(r1.text)
                if not viewstate:
                    continue

                checkbox_id = find_checkbox_id(r1.text)

                ajax_headers['Referer'] = HOMEPAGE_URL
                time.sleep(1)
                r2 = session.post(HOMEPAGE_BASE, data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': 'fit_c_office_to',
                    'javax.faces.partial.execute': 'fit_c_office_to',
                    'javax.faces.behavior.event': 'change',
                    'javax.faces.partial.event': 'change',
                    'homepageformid': 'homepageformid',
                    'fit_c_office_to_input': '1',
                    'javax.faces.ViewState': viewstate,
                }, headers=ajax_headers, timeout=45)
                viewstate = extract_viewstate_from_ajax(r2.text) or viewstate

                time.sleep(1)
                r3 = session.post(HOMEPAGE_BASE, data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': checkbox_id,
                    'javax.faces.partial.execute': checkbox_id,
                    'javax.faces.partial.render': 'proccedHomeButtonId',
                    'javax.faces.behavior.event': 'change',
                    'homepageformid': 'homepageformid',
                    f'{checkbox_id}_input': 'on',
                    'javax.faces.ViewState': viewstate,
                }, headers=ajax_headers, timeout=45)
                viewstate = extract_viewstate_from_ajax(r3.text) or viewstate

                time.sleep(1)
                r4 = session.post(HOMEPAGE_BASE, data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': 'proccedHomeButtonId',
                    'javax.faces.partial.execute': '@all',
                    'proccedHomeButtonId': 'proccedHomeButtonId',
                    'homepageformid': 'homepageformid',
                    f'{checkbox_id}_input': 'on',
                    'javax.faces.ViewState': viewstate,
                }, headers=ajax_headers, timeout=45)
                viewstate = extract_viewstate_from_ajax(r4.text) or viewstate

                time.sleep(1)
                dialog_match = re.search(r'id="(j_idt\d+)"[^>]*class="[^"]*ui-button', r4.text)
                dialog_btn = dialog_match.group(1) if dialog_match else "j_idt536"
                r5 = session.post(HOMEPAGE_BASE, data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': dialog_btn,
                    'javax.faces.partial.execute': '@all',
                    f'{dialog_btn}': dialog_btn,
                    'homepageformid': 'homepageformid',
                    f'{checkbox_id}_input': 'on',
                    'javax.faces.ViewState': viewstate,
                }, headers=ajax_headers, timeout=45)
                viewstate = extract_viewstate_from_ajax(r5.text) or viewstate

                time.sleep(1)
                r6 = session.get(LOGIN_URL + "?faces-redirect=true", timeout=45, allow_redirects=True)
                viewstate = extract_viewstate(r6.text)
                if not viewstate:
                    continue

                time.sleep(1)
                fit_match = re.search(r'id="(j_idt\d+)"[^>]*name="\1"[^>]*type="submit"', r6.text)
                fit_btn = fit_match.group(1) if fit_match else "j_idt506"
                post_headers = {
                    **session.headers,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://vahan.parivahan.gov.in',
                    'Referer': LOGIN_URL + "?faces-redirect=true",
                }
                r7 = session.post(LOGIN_URL, data={
                    'loginForm': 'loginForm',
                    f'{fit_btn}': fit_btn,
                    'javax.faces.ViewState': viewstate,
                    'fitbalcTest': 'fitbalcTest',
                    'pur_cd': '86',
                }, headers=post_headers, timeout=45, allow_redirects=True)

                time.sleep(1)
                form_headers = {**session.headers, 'Referer': LOGIN_URL + "?faces-redirect=true"}
                r8 = session.get(FORM_URL, headers=form_headers, timeout=45)
                viewstate = extract_viewstate(r8.text)
                if not viewstate:
                    continue

                time.sleep(1)
                ajax_headers['Referer'] = FORM_URL
                r9 = session.post(FORM_URL, data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': 'balanceFeesFine:validate_dtls',
                    'javax.faces.partial.execute': '@all',
                    'javax.faces.partial.render': 'balanceFeesFine:auth_panel',
                    'balanceFeesFine:validate_dtls': 'balanceFeesFine:validate_dtls',
                    'balanceFeesFine': 'balanceFeesFine',
                    'balanceFeesFine:tf_reg_no': vehicle_number,
                    'balanceFeesFine:tf_chasis_no': chassis_last_5,
                    'javax.faces.ViewState': viewstate,
                }, headers=ajax_headers, timeout=45)

                text = r9.text

                for pat in [r'id="balanceFeesFine:tf_mobile"[^>]*value="(\d{10})"',
                            r'value="(\d{10})"[^>]*id="balanceFeesFine:tf_mobile"',
                            r'balanceFeesFine:tf_mobile[^>]*value="(\d{10})"']:
                    m = re.search(pat, text, re.DOTALL)
                    if m and m.group(1)[0] in '6789':
                        return {"success": True, "mobile_number": m.group(1)}

                fallback = re.findall(r'\b[6-9]\d{9}\b', text)
                if fallback:
                    return {"success": True, "mobile_number": fallback[0]}

            except Exception as e:
                print(f"Error: {e}")
                time.sleep(3)

    if fallback_mobile and len(fallback_mobile) == 10 and fallback_mobile[0] in '6789':
        return {"success": True, "mobile_number": fallback_mobile}

    return {"success": False, "error": "Mobile number not found"}

@app.route("/fetch", methods=["GET"])
def fetch_contact():
    api_key = request.args.get("api_key", "")
    
    if datetime.now() > EXPIRY_DATE:
        return jsonify({
            "success": False,
            "error": "API subscription has expired",
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 403
    
    if api_key != "Cutie":
        return jsonify({
            "success": False,
            "error": "Invalid API key",
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 401
    
    vehicle_number = request.args.get("vehicle_number", "").strip().upper()
    vehicle_number = re.sub(r'[^A-Z0-9]', '', vehicle_number)

    if not vehicle_number or len(vehicle_number) < 6 or len(vehicle_number) > 12:
        return jsonify({
            "success": False,
            "error": "Invalid vehicle number",
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 400

    smc_result = get_vehicle_details_from_smc(vehicle_number)

    if not smc_result["success"]:
        return jsonify({
            "success": False,
            "error": smc_result["error"],
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 400

    mobile_result = fetch_mobile_number(
        vehicle_number,
        smc_result["chassis_last_5"],
        smc_result.get("mobile_no", "")
    )

    mobile = None
    if mobile_result["success"]:
        mobile = mobile_result["mobile_number"]
    elif smc_result.get("mobile_no"):
        mobile = smc_result["mobile_no"]

    if mobile:
        vehicle_data = smc_result.get("vehicle_data", {})
        vehicle_data["mobile_no"] = mobile
        vehicle_data.pop("transKey", None)
        vehicle_data["owner"] = "@PurelyYour | Buy Instantly at the Best Price"
        return jsonify({
            "statusCode": 200,
            "response": vehicle_data
        })

    return jsonify({
        "success": False,
        "error": mobile_result["error"],
        "owner": "@PurelyYour | Buy Instantly at the Best Price"
    }), 400

@app.route("/")
def home():
    return jsonify({
        "status": "API Running",
        "usage": "/fetch?vehicle_number=XX00XX0000&api_key=Cutie",
        "owner": "@PurelyYour | Buy Instantly at the Best Price"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
