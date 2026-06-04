from flask import Flask, request, jsonify
import requests
import re
import time
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta

app = Flask(__name__)

# Set expiration date - 31 days from now
EXPIRY_DATE = datetime.now() + timedelta(days=31)

SMC_HOMEPAGE = "https://www.smcinsurance.com/"
SMC_API = "https://www.smcinsurance.com/central/centralcall/CallReqWithHeader"

HOMEPAGE_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml?statecd=Mzc2MzYzMDMzNjY0MzIzODM3NjIzNjY0MzY2MjM3NDQ0Yw=="
HOMEPAGE_BASE = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml"
LOGIN_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/usermgmt/login.xhtml"
FORM_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/balanceservice/form_reschedule_fitness.xhtml"

def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    })
    return session

def get_vehicle_details_from_smc(vehicle_number):
    try:
        with requests.Session() as s:
            s.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
            })
            
            home = s.get(SMC_HOMEPAGE, timeout=30, verify=True)
            home.raise_for_status()

            mcbc_cookie = s.cookies.get("MCBC")

            if not mcbc_cookie:
                return {"success": False, "error": "MCBC cookie not found"}

            payload = {
                "url": "GetVaahanDetailsByVehicleNo",
                "props": [
                    vehicle_number,
                    "",
                    "0"
                ]
            }

            headers = {
                "Content-Type": "application/json",
                "User-Agent": "okhttp/4.9.2",
                "Cookie": f"MCBC={mcbc_cookie}",
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br",
            }

            response = s.post(
                SMC_API,
                headers=headers,
                json=payload,
                timeout=30
            )

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
                return {"success": False, "error": "Chassis too short or not found"}

            return {"success": False, "error": "SMC API returned no data"}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "SMC API timeout - server is slow"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to SMC API"}
    except Exception as e:
        return {"success": False, "error": f"SMC Error: {str(e)}"}

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
    session = create_session()

    ajax_headers = {
        'Accept': 'application/xml, text/xml, */*; q=0.01',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Faces-Request': 'partial/ajax',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': 'https://vahan.parivahan.gov.in',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    for attempt in range(3):  # Increased to 3 attempts
        try:
            print(f"Attempt {attempt + 1} for vehicle {vehicle_number}")
            
            # Step 1: Get homepage
            r1 = session.get(HOMEPAGE_URL, timeout=45)
            if r1.status_code != 200:
                print(f"Homepage failed: {r1.status_code}")
                time.sleep(3)
                continue
                
            viewstate = extract_viewstate(r1.text)
            if not viewstate:
                print("No viewstate in homepage")
                time.sleep(3)
                continue

            checkbox_id = find_checkbox_id(r1.text)
            print(f"Got viewstate and checkbox: {checkbox_id}")

            # Step 2: Office selection
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

            # Step 3: Checkbox
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

            # Step 4: Proceed button
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

            # Step 5: Dialog button
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

            # Step 6: Login page
            time.sleep(1)
            r6 = session.get(LOGIN_URL + "?faces-redirect=true", timeout=45, allow_redirects=True)
            viewstate = extract_viewstate(r6.text)
            if not viewstate:
                print("No viewstate in login page")
                time.sleep(3)
                continue

            # Step 7: Submit login
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

            # Step 8: Form page
            time.sleep(1)
            form_headers = {**session.headers, 'Referer': LOGIN_URL + "?faces-redirect=true"}
            r8 = session.get(FORM_URL, headers=form_headers, timeout=45)
            viewstate = extract_viewstate(r8.text)
            if not viewstate:
                print("No viewstate in form page")
                time.sleep(3)
                continue

            # Step 9: Validate and get mobile
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
            
            # Check for mobile number in response
            if 'tf_mobile' in text:
                print("Mobile field found in response")
            
            # Try multiple patterns
            patterns = [
                r'id="balanceFeesFine:tf_mobile"[^>]*value="(\d{10})"',
                r'value="(\d{10})"[^>]*id="balanceFeesFine:tf_mobile"',
                r'balanceFeesFine:tf_mobile[^>]*value="(\d{10})"',
                r'name="balanceFeesFine:tf_mobile"[^>]*value="(\d{10})"',
            ]
            
            for pat in patterns:
                m = re.search(pat, text, re.DOTALL)
                if m and m.group(1)[0] in '6789':
                    print(f"Found mobile: {m.group(1)}")
                    return {"success": True, "mobile_number": m.group(1)}

            # Fallback: find any 10-digit number starting with 6-9
            fallback = re.findall(r'\b[6-9]\d{9}\b', text)
            if fallback:
                print(f"Found fallback mobile: {fallback[0]}")
                return {"success": True, "mobile_number": fallback[0]}

            print(f"No mobile found in attempt {attempt + 1}")
            
        except requests.exceptions.Timeout:
            print(f"Timeout in attempt {attempt + 1}")
        except requests.exceptions.ConnectionError:
            print(f"Connection error in attempt {attempt + 1}")
        except Exception as e:
            print(f"Error in attempt {attempt + 1}: {str(e)}")

        # Wait longer between attempts
        time.sleep(5)

    # If all attempts failed, return fallback mobile if valid
    if fallback_mobile and len(fallback_mobile) == 10 and fallback_mobile[0] in '6789':
        print(f"Using fallback mobile: {fallback_mobile}")
        return {"success": True, "mobile_number": fallback_mobile}

    return {"success": False, "error": "Mobile number not found after multiple attempts"}

@app.route("/fetch", methods=["GET"])
def fetch_contact():
    # Check API key
    api_key = request.args.get("api_key", "")
    
    # Check if API has expired
    if datetime.now() > EXPIRY_DATE:
        return jsonify({
            "success": False, 
            "error": "API subscription has expired",
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 403
    
    # Validate API key
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

    # First try SMC API
    smc_result = get_vehicle_details_from_smc(vehicle_number)

    if not smc_result["success"]:
        return jsonify({
            "success": False, 
            "error": smc_result["error"],
            "owner": "@PurelyYour | Buy Instantly at the Best Price"
        }), 400

    # Then try to get mobile from Vahan
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
        "error": "Mobile number not found",
        "owner": "@PurelyYour | Buy Instantly at the Best Price"
    }), 400

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "API is running",
        "endpoint": "/fetch",
        "parameters": {
            "vehicle_number": "Vehicle registration number",
            "api_key": "API key for authentication"
        },
        "owner": "@PurelyYour | Buy Instantly at the Best Price"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
