"""
01_ivr_menu/server.py — Vobiz IVR (Real-world multi-level menu)
================================================================
Main Menu:
  1 → Sales          (learn about products / request demo / speak to sales)
  2 → Tech Support   (API issues / call quality / account access)
  3 → Billing        (check balance / payment issues / invoice queries)
  4 → Account Mgmt   (upgrade plan / cancel / update details)
  0 → Operator       (direct transfer)
  9 → Repeat menu

YOUR APP API:
  GET  /config                     → view department config
  PUT  /config/department/{dept}   → update transfer number
  GET  /call-logs                  → full call history
  GET  /call-logs/analytics        → which options are pressed most
"""

import os
import logging
import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from menu_config import MenuConfig

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
FROM_NUMBER = os.getenv("FROM_NUMBER", "")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("vobiz_ivr")

app = FastAPI(title="Vobiz IVR")
BASE_URL: str = ""
menu = MenuConfig(default_operator_number=FROM_NUMBER)


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


# ===========================================================================
# YOUR APP API
# ===========================================================================


class DeptUpdate(BaseModel):
    number: str = None
    enabled: bool = None
    name: str = None


@app.get("/config")
async def get_config():
    return JSONResponse(menu.get_all())


@app.put("/config/department/{dept_id}")
async def update_department(dept_id: str, body: DeptUpdate):
    ok = menu.update_department(
        dept_id, number=body.number, enabled=body.enabled, name=body.name
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Department '{dept_id}' not found")
    return JSONResponse(
        {"status": "updated", "department": menu.get_all().get(dept_id)}
    )


@app.get("/call-logs")
async def call_logs():
    return JSONResponse(menu.get_logs())


@app.get("/call-logs/analytics")
async def call_logs_analytics():
    return JSONResponse(menu.get_analytics())


# ===========================================================================
# VOBIZ WEBHOOKS — IVR call flow
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    logger.info(
        f"Incoming call — CallUUID={form.get('CallUUID', '?')}, From={form.get('From', '?')}"
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-main-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Welcome to Vobiz, India's leading cloud telephony platform.
            For Sales, press 1.
            For Technical Support, press 2.
            For Billing and Payments, press 3.
            For Account Management, press 4.
            To speak to an operator, press 0.
            To repeat this menu, press 9.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">
        We did not receive your input. Please call us back. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-main-choice")
async def ivr_main_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = form.get("CallUUID", "unknown")
    from_num = form.get("From", "unknown")

    dept_map = {
        "1": "sales",
        "2": "support",
        "3": "billing",
        "4": "account",
        "0": "operator",
    }
    dept = dept_map.get(digit)
    menu.log_call(call_uuid, from_num, digit, department=dept)
    logger.info(f"Main choice digit={digit} dept={dept} uuid={call_uuid}")

    routes = {
        "1": f"{BASE_URL}/ivr-sales",
        "2": f"{BASE_URL}/ivr-support",
        "3": f"{BASE_URL}/ivr-billing",
        "4": f"{BASE_URL}/ivr-account",
        "0": f"{BASE_URL}/ivr-operator",
        "9": f"{BASE_URL}/answer",
    }
    target = routes.get(digit, f"{BASE_URL}/answer")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{target}</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# SALES SUB-MENU
# ===========================================================================


@app.post("/ivr-sales")
async def ivr_sales(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-sales-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            You have reached the Vobiz Sales team.
            To learn about our cloud telephony products and pricing, press 1.
            To request a free product demo, press 2.
            To speak directly with a sales executive, press 3.
            To return to the main menu, press 9.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-sales</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-sales-choice")
async def ivr_sales_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    dept = menu.get_department("sales")
    number = dept.number if dept and dept.number else FROM_NUMBER

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Vobiz offers outbound calling, inbound IVR, SMS, AI voice agents,
        and SIP trunking solutions starting at just one rupee per minute.
        For detailed pricing, visit vobiz dot ai slash pricing.
        Returning to the sales menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/ivr-sales</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        We would love to show you Vobiz in action!
        To book a free demo, please visit vobiz dot ai slash demo,
        or our team will reach out to you within one business day.
        Thank you for your interest in Vobiz!
    </Speak>
    <Hangup/>
</Response>"""
    elif digit == "3":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Please hold while we connect you to a Vobiz sales executive.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=sales" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        Our sales team is currently unavailable. Please call back during business hours,
        Monday to Friday, 9 AM to 6 PM. Returning to the main menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
    elif digit == "9":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-sales</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# TECHNICAL SUPPORT SUB-MENU
# ===========================================================================


@app.post("/ivr-support")
async def ivr_support(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-support-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            You have reached Vobiz Technical Support.
            For API and integration issues, press 1.
            For call quality or connectivity issues, press 2.
            For account access or login problems, press 3.
            To return to the main menu, press 9.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-support</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-support-choice")
async def ivr_support_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    dept = menu.get_department("support")
    number = dept.number if dept and dept.number else FROM_NUMBER

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        For API and integration support, please visit our developer documentation
        at docs dot vobiz dot ai. You can also raise a support ticket at
        support dot vobiz dot ai. Our technical team responds within 4 hours.
    </Speak>
    <Gather action="{BASE_URL}/ivr-support-ticket" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="8">
        <Speak voice="WOMAN" language="en-US">
            To raise a high priority ticket right now, press 1.
            To return to the support menu, press 9.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-support</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Please hold while we connect you to a Vobiz network engineer.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=support" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        Our network team is currently unavailable. Please email support at vobiz dot ai
        with your call UUID and we will investigate. Returning to the main menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
    elif digit == "3":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        For account access issues, please visit vobiz dot ai slash reset-password,
        or email support at vobiz dot ai with your registered mobile number.
        Our team will resolve it within 2 hours. Returning to the support menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/ivr-support</Redirect>
</Response>"""
    elif digit == "9":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-support</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-support-ticket")
async def ivr_support_ticket(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Your high priority support ticket has been raised. A Vobiz engineer
        will contact you on this number within 30 minutes. Thank you!
    </Speak>
    <Hangup/>
</Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-support</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# BILLING SUB-MENU
# ===========================================================================


@app.post("/ivr-billing")
async def ivr_billing(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-billing-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            You have reached Vobiz Billing.
            To check your account balance and usage, press 1.
            For payment failures or recharge issues, press 2.
            For invoice and GST queries, press 3.
            To return to the main menu, press 9.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-billing</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-billing-choice")
async def ivr_billing_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    dept = menu.get_department("billing")
    number = dept.number if dept and dept.number else FROM_NUMBER

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        You can check your real-time balance and usage on the Vobiz dashboard
        at app dot vobiz dot ai. Balance alerts can be configured under
        account settings. Returning to the billing menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/ivr-billing</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Connecting you to our billing team for payment assistance.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=billing" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        Our billing team is unavailable. Please email billing at vobiz dot ai
        with your transaction ID. We will resolve it within 24 hours.
    </Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
    elif digit == "3":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        All invoices and GST certificates are available for download from
        the Vobiz dashboard under Billing, then Invoices.
        For custom invoice requests, please email billing at vobiz dot ai.
        Returning to the billing menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/ivr-billing</Redirect>
</Response>"""
    elif digit == "9":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-billing</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# ACCOUNT MANAGEMENT SUB-MENU
# ===========================================================================


@app.post("/ivr-account")
async def ivr_account(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-account-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            You have reached Vobiz Account Management.
            To upgrade your plan, press 1.
            To update your registered details, press 2.
            To request account cancellation, press 3.
            To return to the main menu, press 9.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-account</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-account-choice")
async def ivr_account_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    dept = menu.get_department("account")
    number = dept.number if dept and dept.number else FROM_NUMBER

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Vobiz offers Starter, Growth, and Enterprise plans.
        You can upgrade instantly from the dashboard at app dot vobiz dot ai
        under Settings, then Plan and Billing.
        Connecting you to our account team for further assistance.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=account" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        Our team is unavailable right now. Please visit the dashboard to upgrade.
    </Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        To update your registered email, mobile number, or business details,
        please visit app dot vobiz dot ai under Settings, then Profile.
        For KYC updates, please email accounts at vobiz dot ai with your documents.
        Returning to the account menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/ivr-account</Redirect>
</Response>"""
    elif digit == "3":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/ivr-account-cancel-confirm" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="8">
        <Speak voice="WOMAN" language="en-US">
            We are sorry to hear you want to cancel your Vobiz account.
            Before you go, our team would love to help resolve any issues.
            To confirm cancellation, press 1.
            To speak with a retention specialist instead, press 2.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/ivr-account</Redirect>
</Response>"""
    elif digit == "9":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-account</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/ivr-account-cancel-confirm")
async def ivr_account_cancel_confirm(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    dept = menu.get_department("account")
    number = dept.number if dept and dept.number else FROM_NUMBER

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Your cancellation request has been submitted. You will receive a confirmation
        email within 24 hours. Your account will remain active until the end of
        the current billing cycle. Thank you for using Vobiz. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Connecting you to a Vobiz retention specialist. Please hold.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=account" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        Our team is unavailable. We will call you back within 2 hours.
    </Speak>
    <Hangup/>
</Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/ivr-account</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# OPERATOR — direct transfer
# ===========================================================================


@app.post("/ivr-operator")
async def ivr_operator(request: Request):
    dept = menu.get_department("operator")
    number = dept.number if dept and dept.number else FROM_NUMBER
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Please hold while we connect you to a Vobiz operator.
    </Speak>
    <Dial action="{BASE_URL}/dial-complete?dept=operator" method="POST"
          timeout="30" timeLimit="600" callerId="{FROM_NUMBER}">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        All our operators are currently busy. Please call back during business hours,
        Monday to Friday, 9 AM to 6 PM. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
# SHARED DIAL CALLBACK
# ===========================================================================


@app.post("/dial-complete")
async def dial_complete(request: Request):
    form = await request.form()
    status = form.get("DialStatus", "unknown")
    call_uuid = form.get("CallUUID", "unknown")
    dept = request.query_params.get("dept", "unknown")
    menu.update_dial_status(call_uuid, status)
    logger.info(f"Dial complete — dept={dept}, status={status}, uuid={call_uuid}")
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you for calling Vobiz. Have a great day. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    logger.info(f"Call ended — CallUUID={form.get('CallUUID', '?')}")
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "base_url": BASE_URL, "example": "01_ivr_menu"}


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  Vobiz IVR — Multi-Level Menu")
    logger.info(f"  Answer URL  : {BASE_URL}/answer")
    logger.info(f"  Hangup URL  : {BASE_URL}/hangup")
    logger.info(f"  Config      : GET/PUT {BASE_URL}/config")
    logger.info(f"  Analytics   : GET {BASE_URL}/call-logs/analytics")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
