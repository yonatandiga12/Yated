import pandas as pd
import streamlit as st
from datetime import date

from yated.constants import (
    DAYS_OPTIONS,
    PAYMENT_METHOD_OPTIONS,
    SCHOLARSHIP_OPTIONS,
    MONTHS_NOV_JUL,
    MORNING_FRAMEWORK_OPTIONS,
)
from yated import constants as yated_constants
from yated.sheets import (
    DEFAULT_SPREADSHEET_ID,
    build_sheets_service,
    ensure_sheets,
    read_sheet_as_df,
    write_df_to_sheet,
    get_credentials,
)
from yated.meta import get_meta, set_meta, META_SHEET
from yated.participants import (
    apply_participant_rules,
    build_morning_framework_alert_mask,
    compute_age_column,
    compute_required_payment,
    normalize_attendance_for_editor,
    normalize_days_for_editor,
    normalize_media_consent_for_editor,
    normalize_media_consent_for_save,
)
from yated.staff import (
    apply_hourly_totals,
    apply_staff_details_rules,
    build_staff_backup_df,
    compute_remaining_hours,
    compute_hourly_totals,
    derive_transportation_from_scholarship,
    derive_weekly_hours_from_scholarship,
    normalize_police_clearance_for_editor,
    normalize_police_clearance_for_save,
    should_rollover,
    summarize_staff_by_scholarship,
)
from yated.attendance import (
    build_participant_daily_attendance,
    build_staff_daily_attendance,
    summarize_participant_attendance_yearly,
    summarize_staff_hours,
)
from yated.payments import build_billing_table

ROLE_OPTIONS = getattr(yated_constants, "ROLE_OPTIONS", ["Madrich", "Madrich Miktzoi"])
TRANSPORTATION_OPTIONS = getattr(
    yated_constants,
    "TRANSPORTATION_OPTIONS",
    ["Ofakim", "Beer Sheva", "Haloch", "Hazor"],
)


st.set_page_config(page_title="Yated CRM", layout="wide")


PARTICIPANTS_SHEET = "Participants"
PARTICIPANTS_ATTENDANCE_SHEET = "Participants_Attendance"
PARTICIPANTS_ATTENDANCE_SUMMARY = "Participants_Attendance_Summary"
PARTICIPANTS_BACKUP = "Participants_Yearly_Backup"
PARTICIPANTS_SUMMARY = "Participants_Summary"

STAFF_DETAILS_SHEET = "Staff_Details"
STAFF_BACKUP_SHEET = "Staff_Backup"
STAFF_SUMMARY_SHEET = "Staff_Summary"

STAFF_ATTENDANCE_SHEET = "Staff_Attendance"
STAFF_ATTENDANCE_TOTALS = "Staff_Attendance_Totals"

PAYMENTS_SHEET = "Payments"
BILLING_SHEET = "Billing"


@st.cache_data(show_spinner=False, ttl=30)
def read_df_cached(_service, spreadsheet_id: str, sheet: str) -> pd.DataFrame:
    return read_sheet_as_df(_service, spreadsheet_id, sheet)


def write_df(_service, spreadsheet_id: str, sheet: str, df: pd.DataFrame) -> None:
    write_df_to_sheet(_service, spreadsheet_id, sheet, df)
    st.cache_data.clear()


def ensure_required_sheets(_service, spreadsheet_id: str) -> None:
    ensure_sheets(
        _service,
        spreadsheet_id,
        [
            META_SHEET,
            PARTICIPANTS_SHEET,
            PARTICIPANTS_ATTENDANCE_SHEET,
            PARTICIPANTS_ATTENDANCE_SUMMARY,
            PARTICIPANTS_BACKUP,
            PARTICIPANTS_SUMMARY,
            STAFF_DETAILS_SHEET,
            STAFF_BACKUP_SHEET,
            STAFF_SUMMARY_SHEET,
            STAFF_ATTENDANCE_SHEET,
            STAFF_ATTENDANCE_TOTALS,
            PAYMENTS_SHEET,
            BILLING_SHEET,
        ],
    )


def get_weekday_name(d: date) -> str:
    return d.strftime("%A")


def upsert_date_rows(base_df: pd.DataFrame, date_col: str, day_value: str, new_rows: pd.DataFrame) -> pd.DataFrame:
    if base_df.empty:
        return new_rows.copy()
    out = base_df.copy()
    if date_col in out.columns:
        out = out[out[date_col].astype(str) != day_value]
    out = pd.concat([out, new_rows], ignore_index=True)
    return out


def build_and_sync_participant_summary(_service, spreadsheet_id: str) -> pd.DataFrame:
    participants_df = read_df_cached(_service, spreadsheet_id, PARTICIPANTS_SHEET)
    attendance_df = read_df_cached(_service, spreadsheet_id, PARTICIPANTS_ATTENDANCE_SHEET)
    year = date.today().year
    summary_df = summarize_participant_attendance_yearly(
        attendance_df=attendance_df,
        participants_df=participants_df,
        year=year,
        participants_serial_col="Serial Number",
        participants_name_col="First Name",
        participants_last_name_col="Last Name",
        participants_attendance_col="Attendance",
        attendance_serial_col="Serial Number",
        attended_col="Attended",
    )
    existing_summary = read_df_cached(_service, spreadsheet_id, PARTICIPANTS_ATTENDANCE_SUMMARY)
    left = summary_df.fillna("").astype(str)
    right = existing_summary.fillna("").astype(str) if not existing_summary.empty else pd.DataFrame()
    if left.to_dict("records") != right.to_dict("records"):
        write_df(_service, spreadsheet_id, PARTICIPANTS_ATTENDANCE_SUMMARY, summary_df)
    return summary_df


with st.sidebar:
    st.title("Yated CRM")
    spreadsheet_id = st.secrets.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)
    refresh = st.button("Refresh data")
    page = st.radio(
        "Section",
        [
            "Participants",
            "Participant Attendance",
            "Participant Attendance Summary",
            "Staff Details",
            "Staff Backup",
            "Staff Attendance",
            "Payments",
            "Billing",
            "Admin",
        ],
    )

try:
    creds = get_credentials()
    service = build_sheets_service(creds)
    ensure_required_sheets(service, spreadsheet_id)
except Exception as e:
    st.error(str(e))
    st.stop()

if refresh:
    st.cache_data.clear()


if page == "Participants":
    st.header("Participant Details")

    cols = [
        "Alert",
        "Serial Number",
        "First Name",
        "Last Name",
        "ID Number",
        "Date of Birth",
        "Age",
        "Allergies",
        "Morning Framework",
        "Mother Name",
        "Mother Phone",
        "Father Name",
        "Father Phone",
        "Media Consent",
        "Media Consent Year",
        "Pickup Address",
        "Drop-off Address",
        "Attendance",
        "Attendance Days",
        "Required Payment",
        "T-shirt Size",
        "Special Notes",
    ]

    df = read_df_cached(service, spreadsheet_id, PARTICIPANTS_SHEET)
    if df.empty:
        df = pd.DataFrame(columns=cols)

    base_cols = list(df.columns)
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    df = df[cols]
    df = normalize_days_for_editor(df, days_col="Attendance Days")
    df = normalize_attendance_for_editor(df, attendance_col="Attendance")
    df = compute_age_column(df, birthdate_col="Date of Birth", age_col="Age")
    df = compute_required_payment(df, days_col="Attendance Days", payment_col="Required Payment")
    if "Date of Birth" in df.columns:
        df["Date of Birth"] = pd.to_datetime(df["Date of Birth"], errors="coerce")

    current_year = date.today().year
    consent_state = normalize_media_consent_for_editor(
        df,
        consent_col="Media Consent",
        year_col="Media Consent Year",
        current_year=current_year,
    )
    df = consent_state.df
    if "Media Consent" in df.columns:
        def _to_bool(v: object) -> bool:
            if isinstance(v, bool):
                return v
            s = "" if v is None else str(v).strip().lower()
            return s in {"true", "1", "✓", "yes", "y"}

        df["Media Consent"] = df["Media Consent"].map(_to_bool).fillna(False).astype(bool)

    with st.expander("Add New Participant", expanded=False):
        with st.form("add_participant_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                first_name = st.text_input("First Name")
                last_name = st.text_input("Last Name")
                id_number = st.text_input("ID Number")
                dob = st.date_input("Date of Birth", value=None)
                attendance = st.checkbox("Attendance (checked = attending)", value=True)
            with c2:
                allergies = st.text_input("Allergies")
                morning_framework = st.selectbox("Morning Framework", options=[""] + MORNING_FRAMEWORK_OPTIONS)
                mother_name = st.text_input("Mother Name")
                mother_phone = st.text_input("Mother Phone")
                father_name = st.text_input("Father Name")
            with c3:
                father_phone = st.text_input("Father Phone")
                media_consent = st.checkbox("Media Consent (current year)", value=False)
                pickup = st.text_input("Pickup Address")
                dropoff = st.text_input("Drop-off Address")
                attendance_days = st.multiselect("Attendance Days", options=DAYS_OPTIONS, default=[])
                tshirt = st.text_input("T-shirt Size")
                notes = st.text_area("Special Notes", height=80)

            submit_new = st.form_submit_button("Add Participant")

        if submit_new:
            new_row = {
                "Serial Number": "",
                "First Name": first_name,
                "Last Name": last_name,
                "ID Number": id_number,
                "Date of Birth": dob.isoformat() if dob else "",
                "Age": "",
                "Allergies": allergies,
                "Morning Framework": morning_framework,
                "Mother Name": mother_name,
                "Mother Phone": mother_phone,
                "Father Name": father_name,
                "Father Phone": father_phone,
                "Media Consent": media_consent,
                "Media Consent Year": "",
                "Pickup Address": pickup,
                "Drop-off Address": dropoff,
                "Attendance": attendance,
                "Attendance Days": attendance_days,
                "Required Payment": "",
                "T-shirt Size": tshirt,
                "Special Notes": notes,
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            try:
                current_year = date.today().year
                df_to_save = normalize_media_consent_for_save(
                    df,
                    consent_col="Media Consent",
                    year_col="Media Consent Year",
                    current_year=current_year,
                )
                out = apply_participant_rules(
                    df_to_save,
                    id_col="Serial Number",
                    birthdate_col="Date of Birth",
                    age_col="Age",
                    days_col="Attendance Days",
                    payment_col="Required Payment",
                    attendance_col="Attendance",
                    consent_col="Media Consent",
                    consent_year_col="Media Consent Year",
                    current_year=current_year,
                    name_cols=["First Name", "Last Name"],
                )
                write_df(service, spreadsheet_id, PARTICIPANTS_SHEET, out)
                st.success("Participant added.")
            except Exception as e:
                st.error(f"Add failed: {e}")

    morning_alert_mask = build_morning_framework_alert_mask(
        df, birthdate_col="Date of Birth", framework_col="Morning Framework"
    )
    df["Alert"] = ["🔴 ALERT" if x else "" for x in morning_alert_mask]

    edited_df = st.data_editor(
        df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=["Alert", "Serial Number", "Age", "Required Payment"],
        column_config={
            "Alert": st.column_config.TextColumn(
                label="Alert",
                help="ALERT means morning framework age rule is active for this row.",
                width="small",
            ),
            "Morning Framework": st.column_config.SelectboxColumn(
                label="Morning Framework",
                options=MORNING_FRAMEWORK_OPTIONS,
                required=False,
            ),
            "Date of Birth": st.column_config.DateColumn(
                label="Date of Birth",
                format="YYYY-MM-DD",
                required=False,
            ),
            "Attendance Days": st.column_config.MultiselectColumn(
                label="Attendance Days",
                options=DAYS_OPTIONS,
                default=[],
            ),
            "Attendance": st.column_config.CheckboxColumn(
                label="Attendance",
                help="Checked = attending. Unchecked = absent (moves to bottom on save).",
            ),
            "Media Consent": st.column_config.CheckboxColumn(
                label="Media Consent",
                help="Resets every Sep 1. Red = needs confirmation for current year.",
            ),
        },
    )
    flagged_names = []
    if morning_alert_mask and "First Name" in df.columns and "Last Name" in df.columns:
        for idx, is_flagged in enumerate(morning_alert_mask):
            if is_flagged and idx < len(df):
                full_name = f"{df.at[idx, 'First Name']} {df.at[idx, 'Last Name']}".strip()
                flagged_names.append(full_name)
    if flagged_names:
        st.error(
            "Morning framework age alert for: "
            + ", ".join(flagged_names)
            + ". (Age 20 years and 11 months and above in Shahar/Dekalim/Yesodot/Ilanot.)"
        )

    if st.button("Save Participant Details", type="primary"):
        try:
            edited_df = edited_df.reindex(columns=cols, fill_value="")
            if "Alert" in edited_df.columns:
                edited_df = edited_df.drop(columns=["Alert"])
            if "Date of Birth" in edited_df.columns:
                edited_df["Date of Birth"] = pd.to_datetime(edited_df["Date of Birth"], errors="coerce").dt.strftime(
                    "%Y-%m-%d"
                )
                edited_df["Date of Birth"] = edited_df["Date of Birth"].fillna("")
            edited_df = normalize_media_consent_for_save(
                edited_df,
                consent_col="Media Consent",
                year_col="Media Consent Year",
                current_year=current_year,
            )
            out = apply_participant_rules(
                edited_df,
                id_col="Serial Number",
                birthdate_col="Date of Birth",
                age_col="Age",
                days_col="Attendance Days",
                payment_col="Required Payment",
                attendance_col="Attendance",
                consent_col="Media Consent",
                consent_year_col="Media Consent Year",
                current_year=current_year,
                name_cols=["First Name", "Last Name"],
            )
            write_df(service, spreadsheet_id, PARTICIPANTS_SHEET, out)
            st.success("Saved.")
        except Exception as e:
            st.error(f"Save failed: {e}")


if page == "Participant Attendance":
    st.header("Participant Attendance")

    attendance_date = st.date_input("Date", value=date.today())
    day_name = get_weekday_name(attendance_date)

    participants = read_df_cached(service, spreadsheet_id, PARTICIPANTS_SHEET)
    attendance_df = read_df_cached(service, spreadsheet_id, PARTICIPANTS_ATTENDANCE_SHEET)

    if not attendance_df.empty and "Date" in attendance_df.columns:
        existing = attendance_df[attendance_df["Date"].astype(str) == attendance_date.isoformat()]
    else:
        existing = pd.DataFrame()

    if existing.empty:
        if participants.empty:
            st.info("No participants found.")
        else:
            base = build_participant_daily_attendance(
                participants_df=participants,
                attendance_days_col="Attendance Days",
                attendance_flag_col="Attendance",
                serial_col="Serial Number",
                name_col="First Name",
                day_name=day_name,
                attendance_date=attendance_date,
            )
            st.caption("Created a new attendance sheet for this date.")
    else:
        base = existing.copy()

    if not base.empty:
        expected_mask = base["Expected"].astype(str).str.lower() == "yes"
        expected_names = base.loc[expected_mask, "Participant Name"].tolist()
        absent_list = st.multiselect(
            "Who did NOT attend today (from expected list)?",
            options=expected_names,
        )
        if st.button("Apply auto-mark"):
            base["Attended"] = ""
            for idx, row in base.iterrows():
                name = str(row.get("Participant Name", "")).strip()
                expected = str(row.get("Expected", "")).strip().lower() == "yes"
                if expected:
                    base.at[idx, "Attended"] = "No" if name in absent_list else "Yes"

        edited = st.data_editor(
            base,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "Attended": st.column_config.SelectboxColumn(
                    label="Attended",
                    options=["", "Yes", "No"],
                    required=False,
                )
            },
        )

        if st.button("Save Attendance", type="primary"):
            try:
                updated = upsert_date_rows(attendance_df, "Date", attendance_date.isoformat(), edited)
                write_df(service, spreadsheet_id, PARTICIPANTS_ATTENDANCE_SHEET, updated)
                build_and_sync_participant_summary(service, spreadsheet_id)
                st.success("Attendance saved.")
            except Exception as e:
                st.error(f"Save failed: {e}")


if page == "Participant Attendance Summary":
    st.header("Participant Attendance Summary")

    summary_df = build_and_sync_participant_summary(service, spreadsheet_id)
    if summary_df.empty:
        st.info("No active participants with attendance enabled.")
    else:
        st.dataframe(summary_df, width="stretch")
        st.caption("This table updates automatically from submitted Participant Attendance data.")


if page == "Staff Details":
    st.header("Staff Details")

    staff_cols = [
        "Serial Number",
        "First Name",
        "Last Name",
        "Gender",
        "Scholarship",
        "Current Day",
        "Role",
        "Transportation",
        "Weekly Hours",
        "Annual Hours",
        "Hourly Total",
        "Remaining Hours",
        "Police Clearance",
    ]

    staff_df = read_df_cached(service, spreadsheet_id, STAFF_DETAILS_SHEET)
    if staff_df.empty:
        staff_df = pd.DataFrame(columns=staff_cols)
    for c in staff_cols:
        if c not in staff_df.columns:
            staff_df[c] = ""
    staff_df = staff_df[staff_cols]

    attendance_df = read_df_cached(service, spreadsheet_id, STAFF_ATTENDANCE_SHEET)
    totals_map = compute_hourly_totals(attendance_df, serial_col="Serial Number", hours_col="Hours")
    staff_df = apply_hourly_totals(staff_df, "Serial Number", "Hourly Total", totals_map)
    staff_df = compute_remaining_hours(staff_df, "Annual Hours", "Hourly Total", "Remaining Hours")
    staff_df = apply_staff_details_rules(
        staff_df,
        scholarship_col="Scholarship",
        transportation_col="Transportation",
        weekly_hours_col="Weekly Hours",
    )

    police_state = normalize_police_clearance_for_editor(
        staff_df, gender_col="Gender", clearance_col="Police Clearance"
    )
    staff_df = police_state.df
    staff_df["Alert"] = ["ALERT" if x else "" for x in police_state.needs_attention]
    if "Police Clearance" in staff_df.columns:
        def _to_bool(v: object) -> bool:
            if isinstance(v, bool):
                return v
            s = "" if v is None else str(v).strip().lower()
            return s in {"true", "1", "✓", "yes", "y"}

        staff_df["Police Clearance"] = staff_df["Police Clearance"].map(_to_bool).fillna(False).astype(bool)

    edited = st.data_editor(
        staff_df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=["Alert", "Weekly Hours", "Hourly Total", "Remaining Hours"],
        column_config={
            "Alert": st.column_config.TextColumn(
                label="Alert",
                help="ALERT means police clearance is required for this staff row.",
                width="small",
            ),
            "Scholarship": st.column_config.SelectboxColumn(
                label="Scholarship",
                options=sorted(SCHOLARSHIP_OPTIONS),
                required=False,
            ),
            "Role": st.column_config.SelectboxColumn(
                label="Role",
                options=ROLE_OPTIONS,
                required=False,
            ),
            "Current Day": st.column_config.SelectboxColumn(
                label="Current Day",
                options=DAYS_OPTIONS,
                required=False,
            ),
            "Transportation": st.column_config.SelectboxColumn(
                label="Transportation",
                options=["", "X"] + TRANSPORTATION_OPTIONS,
                required=False,
            ),
            "Police Clearance": st.column_config.CheckboxColumn(
                label="Police Clearance",
                help="Required for male staff.",
            ),
        },
    )
    with st.expander("Add New Staff Member", expanded=False):
        with st.form("add_staff_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                first_name = st.text_input("First Name")
                last_name = st.text_input("Last Name")
                gender = st.selectbox("Gender", options=["", "Male", "Female"])
                scholarship = st.selectbox("Scholarship", options=[""] + sorted(SCHOLARSHIP_OPTIONS))
                current_day = st.selectbox("Current Day", options=[""] + DAYS_OPTIONS)
            with c2:
                role = st.selectbox("Role", options=[""] + ROLE_OPTIONS)
                auto_transportation = derive_transportation_from_scholarship(scholarship, "")
                if auto_transportation == "X":
                    transportation = "X"
                    st.text_input("Transportation", value="X", disabled=True)
                else:
                    transportation = st.selectbox("Transportation", options=[""] + TRANSPORTATION_OPTIONS)
                weekly_hours = derive_weekly_hours_from_scholarship(scholarship)
                st.text_input("Weekly Hours (auto)", value=weekly_hours, disabled=True)
                annual_hours = st.text_input("Annual Hours")
            with c3:
                police_clearance = st.checkbox("Police Clearance", value=False)

            submit_staff = st.form_submit_button("Add Staff")

        if submit_staff:
            new_row = {
                "Serial Number": "",
                "First Name": first_name,
                "Last Name": last_name,
                "Gender": gender,
                "Scholarship": scholarship,
                "Current Day": current_day,
                "Role": role,
                "Transportation": transportation,
                "Weekly Hours": weekly_hours,
                "Annual Hours": annual_hours,
                "Hourly Total": "",
                "Remaining Hours": "",
                "Police Clearance": police_clearance,
            }
            staff_df = pd.concat([staff_df, pd.DataFrame([new_row])], ignore_index=True)
            try:
                staff_df = apply_staff_details_rules(
                    staff_df,
                    scholarship_col="Scholarship",
                    transportation_col="Transportation",
                    weekly_hours_col="Weekly Hours",
                )
                to_save = normalize_police_clearance_for_save(staff_df, clearance_col="Police Clearance")
                write_df(service, spreadsheet_id, STAFF_DETAILS_SHEET, to_save)
                st.success("Staff member added.")
            except Exception as e:
                st.error(f"Add failed: {e}")
    if any(police_state.needs_attention):
        st.error("Police clearance is required for male staff members.")

    if st.button("Save Staff Details", type="primary"):
        try:
            edited = edited.reindex(columns=staff_cols, fill_value="")
            if "Alert" in edited.columns:
                edited = edited.drop(columns=["Alert"])
            edited = apply_staff_details_rules(
                edited,
                scholarship_col="Scholarship",
                transportation_col="Transportation",
                weekly_hours_col="Weekly Hours",
            )
            edited = normalize_police_clearance_for_save(edited, clearance_col="Police Clearance")
            write_df(service, spreadsheet_id, STAFF_DETAILS_SHEET, edited)
            st.success("Saved.")
        except Exception as e:
            st.error(f"Save failed: {e}")


if page == "Staff Backup":
    st.header("Staff Backup by Year")
    backup_df = read_df_cached(service, spreadsheet_id, STAFF_BACKUP_SHEET)
    if backup_df.empty:
        st.info("No backup data yet.")
    else:
        st.dataframe(backup_df, width="stretch")


if page == "Staff Attendance":
    st.header("Staff Attendance")

    attendance_date = st.date_input("Date", value=date.today())
    day_name = get_weekday_name(attendance_date)

    staff_df = read_df_cached(service, spreadsheet_id, STAFF_DETAILS_SHEET)
    attendance_df = read_df_cached(service, spreadsheet_id, STAFF_ATTENDANCE_SHEET)

    if not attendance_df.empty and "Date" in attendance_df.columns:
        existing = attendance_df[attendance_df["Date"].astype(str) == attendance_date.isoformat()]
    else:
        existing = pd.DataFrame()

    if existing.empty:
        if staff_df.empty:
            st.info("No staff found.")
        else:
            base = build_staff_daily_attendance(
                staff_df=staff_df,
                current_day_col="Current Day",
                serial_col="Serial Number",
                first_name_col="First Name",
                last_name_col="Last Name",
                scholarship_col="Scholarship",
                day_name=day_name,
                attendance_date=attendance_date,
            )
            st.caption("Created a new attendance sheet for this date.")
    else:
        base = existing.copy()

    if not base.empty:
        expected_mask = base["Expected"].astype(str).str.lower() == "yes"
        expected_names = (base.loc[expected_mask, "First Name"] + " " + base.loc[expected_mask, "Last Name"]).tolist()
        absent_list = st.multiselect(
            "Who did NOT attend today (from expected list)?",
            options=expected_names,
        )
        if st.button("Apply auto-mark staff"):
            base["Attended"] = ""
            for idx, row in base.iterrows():
                name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
                expected = str(row.get("Expected", "")).strip().lower() == "yes"
                if expected:
                    base.at[idx, "Attended"] = "No" if name in absent_list else "Yes"

        edited = st.data_editor(
            base,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "Attended": st.column_config.SelectboxColumn(
                    label="Attended",
                    options=["", "Yes", "No"],
                    required=False,
                )
            },
        )

        if st.button("Save Staff Attendance", type="primary"):
            try:
                updated = upsert_date_rows(attendance_df, "Date", attendance_date.isoformat(), edited)
                write_df(service, spreadsheet_id, STAFF_ATTENDANCE_SHEET, updated)
                totals_df = summarize_staff_hours(updated, serial_col="Serial Number", hours_col="Hours")
                write_df(service, spreadsheet_id, STAFF_ATTENDANCE_TOTALS, totals_df)
                st.success("Attendance saved.")
            except Exception as e:
                st.error(f"Save failed: {e}")


if page == "Payments":
    st.header("Parents' Payments")

    participants = read_df_cached(service, spreadsheet_id, PARTICIPANTS_SHEET)
    payments_df = read_df_cached(service, spreadsheet_id, PAYMENTS_SHEET)

    payment_number = 1
    if not payments_df.empty and "Payment Number" in payments_df.columns:
        try:
            nums = payments_df["Payment Number"].astype(str).str.strip()
            nums_int = [int(n) for n in nums if n.isdigit()]
            if nums_int:
                payment_number = max(nums_int) + 1
        except Exception:
            pass

    with st.form("payment_form"):
        st.subheader("Add Payment")
        participant_ids = participants["Serial Number"].astype(str).tolist() if not participants.empty else []
        selected_id = st.selectbox("Participant Serial", options=participant_ids)
        name = ""
        if selected_id and not participants.empty:
            match = participants[participants["Serial Number"].astype(str) == str(selected_id)]
            if not match.empty:
                name = str(match.iloc[0].get("First Name", ""))
        payment_date = st.date_input("Payment Date", value=date.today())
        amount = st.text_input("Amount")
        method = st.selectbox("Payment Method", options=PAYMENT_METHOD_OPTIONS)
        check_date = st.date_input("Check Date", value=date.today()) if method == "Checks" else None
        submitted = st.form_submit_button("Add Payment")

    if submitted:
        new_row = {
            "Payment Number": str(payment_number),
            "Participant Serial": str(selected_id),
            "Participant Name": name,
            "Payment Date": payment_date.isoformat(),
            "Amount": amount,
            "Payment Method": method,
            "Check Date": check_date.isoformat() if check_date else "",
            "Month": payment_date.strftime("%B"),
        }
        if payments_df.empty:
            payments_df = pd.DataFrame(columns=list(new_row.keys()))
        payments_df = pd.concat([payments_df, pd.DataFrame([new_row])], ignore_index=True)
        write_df(service, spreadsheet_id, PAYMENTS_SHEET, payments_df)
        st.success("Payment added.")

    if not payments_df.empty:
        st.subheader("Payments Table")
        st.dataframe(payments_df, width="stretch")


if page == "Billing":
    st.header("Smart Monthly Billing")

    participants = read_df_cached(service, spreadsheet_id, PARTICIPANTS_SHEET)
    payments_df = read_df_cached(service, spreadsheet_id, PAYMENTS_SHEET)

    if participants.empty:
        st.info("No participants data.")
    else:
        billing = build_billing_table(
            participants_df=participants,
            payments_df=payments_df,
            serial_col="Serial Number",
            name_col="First Name",
            required_col="Required Payment",
            payment_serial_col="Participant Serial",
            payment_amount_col="Amount",
            payment_date_col="Payment Date",
            payment_month_col="Month",
        )

        def _style_partial(val, row_idx, col):
            if (row_idx, col) in billing.partial_mask:
                return "background-color: #ffe699;"
            return ""

        styler = billing.df.style
        for m in MONTHS_NOV_JUL:
            if m in billing.df.columns:
                styler = styler.apply(
                    lambda r: [_style_partial(v, r.name, c) if c == m else "" for c, v in r.items()],
                    axis=1,
                )

        st.dataframe(styler, width="stretch")
        if st.button("Write Billing Table to Sheet"):
            write_df(service, spreadsheet_id, BILLING_SHEET, billing.df)
            st.success("Billing table updated.")


if page == "Admin":
    st.header("Admin")

    meta = get_meta(service, spreadsheet_id)
    last_staff_rollover = meta.get("last_staff_rollover_year")
    try:
        last_staff_rollover_int = int(last_staff_rollover) if last_staff_rollover else None
    except Exception:
        last_staff_rollover_int = None

    if should_rollover(last_staff_rollover_int):
        st.warning("Staff yearly rollover is due (on/after Sep 1).")

    if st.button("Run Staff Annual Rollover"):
        staff_df = read_df_cached(service, spreadsheet_id, STAFF_DETAILS_SHEET)
        if staff_df.empty:
            st.info("No staff data to rollover.")
        else:
            year = date.today().year
            backup_df = build_staff_backup_df(
                staff_df,
                year=year,
                hours_debt_col="Hours Debt",
                remove_cols=["Weekly Hours", "Annual Hours", "Remaining Hours", "Police Clearance", "Hourly Total"],
                year_col="Year",
            )
            backup_existing = read_df_cached(service, spreadsheet_id, STAFF_BACKUP_SHEET)
            combined = (
                pd.concat([backup_existing, backup_df], ignore_index=True)
                if not backup_existing.empty
                else backup_df
            )
            write_df(service, spreadsheet_id, STAFF_BACKUP_SHEET, combined)
            write_df(service, spreadsheet_id, STAFF_DETAILS_SHEET, pd.DataFrame(columns=staff_df.columns))
            summary_df = summarize_staff_by_scholarship(combined, scholarship_col="Scholarship", year_col="Year")
            write_df(service, spreadsheet_id, STAFF_SUMMARY_SHEET, summary_df)
            set_meta(service, spreadsheet_id, {"last_staff_rollover_year": str(year)})
            st.success("Staff rollover completed.")

    if st.button("Archive Participants (Yearly Snapshot)"):
        participants = read_df_cached(service, spreadsheet_id, PARTICIPANTS_SHEET)
        if participants.empty:
            st.info("No participants data.")
        else:
            year = date.today().year
            participants_copy = participants.copy()
            participants_copy["Year"] = str(year)
            backup_existing = read_df_cached(service, spreadsheet_id, PARTICIPANTS_BACKUP)
            combined = (
                pd.concat([backup_existing, participants_copy], ignore_index=True)
                if not backup_existing.empty
                else participants_copy
            )
            write_df(service, spreadsheet_id, PARTICIPANTS_BACKUP, combined)
            summary = (
                combined.groupby("Year").size().reset_index(name="Participants")
                if "Year" in combined.columns
                else pd.DataFrame()
            )
            write_df(service, spreadsheet_id, PARTICIPANTS_SUMMARY, summary)
            st.success("Participants archived.")
