import glob
import json
import os
import unicodedata
import firebase_admin
from firebase_admin import credentials, db
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ==========================================
# 1. FIREBASE CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "serviceAccountKey.json")
LEGACY_SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "serviceAccountKey.json.json")
DATABASE_URL = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://neocare-system-default-rtdb.firebaseio.com/",
)


def find_service_account_file():
    configured_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if configured_file:
        if os.path.isfile(configured_file):
            return configured_file
        raise FileNotFoundError(
            "GOOGLE_APPLICATION_CREDENTIALS points to a file that does not exist: "
            f"'{configured_file}'"
        )

    for candidate in (SERVICE_ACCOUNT_FILE, LEGACY_SERVICE_ACCOUNT_FILE):
        if os.path.isfile(candidate):
            return candidate

    for match in sorted(glob.glob(os.path.join(BASE_DIR, "*serviceAccountKey*.json*"))):
        if os.path.isfile(match):
            return match

    return None


def init_firebase():
    global SERVICE_ACCOUNT_FILE

    resolved_file = find_service_account_file()
    if resolved_file is None:
        raise FileNotFoundError(
            f"Cannot find a Firebase service account JSON in '{BASE_DIR}'. "
            "Set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file "
            "or put the file in the same folder as main.py for local development."
        )

    SERVICE_ACCOUNT_FILE = resolved_file

    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
        firebase_admin.initialize_app(cred, {
            'databaseURL': DATABASE_URL
        })
    print("[SUCCESS] Connected to NEOCARE Firebase Realtime Database!")


# ==========================================
# 2. PEDIATRIC AI ENGINE (Ages 1 - 6 Years)
# ==========================================
def analyze_pediatric_vitals(age_years, hr, spo2, temp, resp_rate, activity):
    """Use the same measurement evaluator as the dashboard and alert pipeline."""
    from assessment import analyze_vitals

    return analyze_vitals(age_years, hr, spo2, temp, resp_rate, activity)


def get_additional_recommendations(age_years, hr, spo2, temp, resp_rate, activity, evaluation):
    if evaluation["risk_status"] == "Critical":
        return []

    if temp >= 38.0:
        return [
            "Record when the fever began and any other symptoms to share with the child's clinician.",
            "If the temperature reading seems unexpected, recheck it according to the thermometer instructions.",
        ]

    if hr > (130 if age_years <= 3 else 115) and activity in ["Resting", "Sleeping"]:
        return [
            "Check the wearable's fit and repeat the reading after the child has been calm and resting.",
            "Note the time, activity, and any symptoms to share with the child's clinician.",
        ]

    if activity == "Active":
        return [
            "Record that the reading was taken during activity and recheck after the child has rested.",
            "If the child seems unwell despite the reading, contact a pediatric clinician.",
        ]

    return [
        "Record the time and activity with each reading so changes are easier to discuss with a clinician.",
        "If the child seems unwell despite reassuring readings, contact a pediatric clinician.",
    ]


# ==========================================
# 3. AUTOMATIC PDF REPORT GENERATOR
# ==========================================
def normalize_report_text(value):
    """Preserve Unicode names and punctuation; remove nonprinting controls."""
    return "".join(
        char for char in unicodedata.normalize("NFC", str(value))
        if unicodedata.category(char) != "Cc" or char in "\n\t"
    )


def configure_report_font(pdf, report_data):
    """Embed the bundled OFL font when Unicode is needed, with Arabic shaping."""
    text = json.dumps(report_data, ensure_ascii=False, default=str)
    if all(ord(char) < 256 for char in text):
        return "Helvetica"
    font_dir = os.path.join(BASE_DIR, "assets", "fonts")
    for style, filename in (("", "Amiri-Regular.ttf"), ("B", "Amiri-Bold.ttf"), ("I", "Amiri-Italic.ttf")):
        pdf.add_font("Amiri", style, os.path.join(font_dir, filename))
    pdf.set_text_shaping(True)
    return "Amiri"


def generate_pdf_report(report_data, filename="NEOCARE_Health_Report.pdf"):
    """
    Creates a structured medical PDF report containing child info, vitals, causes (1,2,3), and recommendations.
    """
    pdf = FPDF()
    report_font = configure_report_font(pdf, report_data)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # Title Header
    pdf.set_font(report_font, "B", 20)
    pdf.set_text_color(0, 128, 128)  # NEOCARE Teal Color
    pdf.cell(
        0, 12, "NEOCARE - Smart Pediatric Health Report",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C"
    )

    pdf.set_font(report_font, "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(
        0, 8, f"Reading received: {report_data['timestamp']}",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C"
    )
    pdf.ln(6)

    # Child Information Section
    pdf.set_font(report_font, "B", 13)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(
        pdf.epw, 8, normalize_report_text(f"Patient Name: {report_data['child_name']}"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.set_font(report_font, "", 11)
    pdf.multi_cell(
        pdf.epw, 7,
        normalize_report_text(f"Age: {report_data['age_years']} Years   |   Activity: {report_data['activity_state']}"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.ln(3)

    # Vital Signs Table
    pdf.set_fill_color(230, 245, 245)
    pdf.set_font(report_font, "B", 11)
    pdf.cell(47, 10, "Heart Rate", border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, "Oxygen (SpO2)", border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, "Temperature", border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, "Resp. Rate", border=1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(report_font, "", 11)
    pdf.cell(47, 10, f"{report_data['heart_rate_bpm']} bpm", border=1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, f"{report_data['spo2_percent']} %", border=1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, f"{report_data['temperature_c']} C", border=1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(47, 10, f"{report_data['respiratory_rate_br_min']} br/min", border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)

    # Rule-based assessment (independent of recommendation generation)
    pdf.set_font(report_font, "B", 13)
    status = report_data["risk_status"]
    if status == "Critical":
        pdf.set_text_color(200, 0, 0)
    elif status == "Warning":
        pdf.set_text_color(210, 120, 0)
    else:
        pdf.set_text_color(0, 140, 60)

    pdf.multi_cell(
        pdf.epw, 8, normalize_report_text(f"Rule-based Assessment: [{status}] - {report_data['condition']}"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.ln(3)

    # Causes (1, 2, 3)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(report_font, "B", 12)
    pdf.cell(0, 8, "Measurement Observations:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(report_font, "", 11)
    for cause in report_data["causes"]:
        pdf.multi_cell(
            pdf.epw, 7, normalize_report_text(f"  {cause}"),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
    pdf.ln(4)

    # Recommendations
    pdf.set_font(report_font, "B", 12)
    local_ai = report_data.get("recommendation_source") == "Local AI (Ollama)"
    urgent_guidance = report_data.get("recommendation_source") == "Rule-based safety guidance"
    recommendation_heading = (
        "Care Recommendations - Local AI (Ollama):" if local_ai
        else "Immediate Rule-based Safety Guidance:" if urgent_guidance
        else "Care Recommendations - Local Rules:"
    )
    pdf.cell(0, 8, recommendation_heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(report_font, "", 11)
    for rec in report_data["recommendations"]:
        pdf.multi_cell(
            pdf.epw, 7, normalize_report_text(f"  * {rec}"),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    if report_data.get("recommendation_notice"):
        pdf.ln(2)
        pdf.multi_cell(
            pdf.epw, 7, normalize_report_text(report_data["recommendation_notice"]),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )

    safety_recommendations = report_data.get("safety_recommendations", [])
    if safety_recommendations:
        pdf.ln(4)
        pdf.set_font(report_font, "B", 12)
        pdf.cell(
            0, 8, "Deterministic Safety Guidance:",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.set_font(report_font, "", 11)
        for rec in safety_recommendations:
            pdf.multi_cell(
                pdf.epw, 7, normalize_report_text(f"  * {rec}"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )

    additional_recommendations = report_data.get("additional_recommendations", [])
    if additional_recommendations:
        pdf.ln(4)
        pdf.set_font(report_font, "B", 12)
        pdf.cell(
            0, 8, "Additional Local Suggestions (not medical advice):",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.set_font(report_font, "", 11)
        pdf.multi_cell(
            pdf.epw, 7,
            "These suggestions are generated locally from simple rules. They do not replace advice from a pediatric clinician.",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        for rec in additional_recommendations:
            pdf.multi_cell(
                pdf.epw, 7, normalize_report_text(f"  * {rec}"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )

    pdf.set_text_color(90, 90, 90)
    pdf.ln(8)
    pdf.set_font(report_font, "I", 9)
    pdf.multi_cell(
        pdf.epw,
        6,
        (
            (
                "AI-generated recommendations were produced locally with Ollama using de-identified readings and may be incorrect. "
                "They are informational only, not medical advice or a diagnosis. Consult a qualified pediatric "
                "clinician for interpretation."
            )
            if local_ai
            else (
                "Urgent guidance is provided immediately from local rules without waiting for AI. "
                "This report is not a medical diagnosis or medical advice. "
                "Consult a qualified pediatric clinician for interpretation."
                if urgent_guidance
                else
                "Local AI recommendations were unavailable; rule-based suggestions are shown instead. "
                "This report is not a medical diagnosis or medical advice. Consult a qualified pediatric "
                "clinician for interpretation."
                if report_data.get("recommendation_source") == "Rule-based fallback"
                else "This rule-based report is not a medical diagnosis or medical advice. "
                "Consult a qualified pediatric clinician for interpretation."
            )
        ),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    if filename is None:
        return bytes(pdf.output())

    output_path = filename if os.path.isabs(filename) else os.path.join(BASE_DIR, filename)
    pdf.output(output_path)
    print(f"[PDF GENERATED] Saved medical report to: {os.path.abspath(output_path)}")
    return None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000)
