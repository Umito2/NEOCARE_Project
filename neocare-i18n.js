/* UI translation only. Patient names, entered notes, and original clinical text are preserved. */
(() => {
  const arabic = {
    "Switch to dark mode": "التبديل إلى الوضع الداكن", "Switch to light mode": "التبديل إلى الوضع الفاتح",
    "Points show recorded measurements. Missing intervals are left blank.": "تمثل النقاط القياسات المسجلة، وتُترك الفترات المفقودة فارغة.",
    "Doctor signed in": "تسجيل دخول طبيب", "Doctor account created": "إنشاء حساب طبيب", "Alert status changed": "تغيير حالة تنبيه", "Clinical note added": "إضافة ملاحظة سريرية", "Alert updated": "تحديث تنبيه", "Alert deleted": "حذف تنبيه", "Child profile created": "إنشاء ملف طفل", "Child profile updated": "تحديث ملف طفل", "Child profile deleted": "حذف ملف طفل", "Clinic thresholds updated": "تحديث حدود العيادة", "Report shared": "مشاركة تقرير",
    "Connected care": "رعاية متصلة", "Skip to dashboard": "الانتقال إلى لوحة المتابعة", "Skip to sign in": "الانتقال إلى تسجيل الدخول",
    "Checking connection": "جارٍ التحقق من الاتصال", "Server connected": "الخادم متصل", "Server unavailable": "الخادم غير متاح", "Sign out": "تسجيل الخروج",
    "Your workspace": "مساحة العمل", "Overview": "نظرة عامة", "Monitoring": "المتابعة", "Alerts & reports": "التنبيهات والتقارير", "Clinic settings": "إعدادات العيادة",
    "A little closer to their care.": "أقرب إلى رعاية أطفالكم.", "Profiles, readings, and reports. All together, in one place.": "الملفات والقراءات والتقارير، معًا في مكان واحد.",
    "A clearer view of care": "رؤية أوضح للرعاية", "Little moments.": "لحظات صغيرة.", "More connected": "رعاية أكثر", "care.": "تواصلًا.",
    "A shared space for families and clinics to follow readings, keep records, and stay informed.": "مساحة مشتركة للأسر والعيادات لمتابعة القراءات وحفظ السجلات والاطلاع على المستجدات.",
    "For families. For care teams.": "للأسر ولفرق الرعاية.", "One shared picture of everyday care.": "صورة مشتركة للرعاية اليومية.", "Welcome to your care space": "مرحبًا بكم في مساحة الرعاية",
    "Welcome to NEOCARE": "مرحبًا بكم في NEOCARE", "Sign in to your parent account or clinic dashboard.": "سجّل الدخول إلى حساب ولي الأمر أو لوحة العيادة.",
    "Account type": "نوع الحساب", "Parent": "ولي الأمر", "Doctor / clinic": "طبيب / عيادة", "Email": "البريد الإلكتروني", "Clinic username": "اسم مستخدم العيادة",
    "Password": "كلمة المرور", "Show": "إظهار", "Hide": "إخفاء", "Show password": "إظهار كلمة المرور", "Hide password": "إخفاء كلمة المرور", "Sign in": "تسجيل الدخول",
    "New to NEOCARE?": "جديد في NEOCARE؟", "Create a parent account": "إنشاء حساب ولي أمر", "Create parent account": "إنشاء حساب ولي أمر", "Create your parent account": "أنشئ حساب ولي الأمر",
    "A few details to get started": "بعض التفاصيل للبدء", "Parent's name": "اسم ولي الأمر", "Email for alerts": "البريد الإلكتروني للتنبيهات", "Phone number": "رقم الهاتف",
    "Password (at least 12 characters)": "كلمة المرور (12 حرفًا على الأقل)", "Child's name": "اسم الطفل", "Age (years)": "العمر (بالسنوات)", "Height (cm)": "الطول (سم)", "Weight (kg)": "الوزن (كجم)",
    "← Back to sign in": "العودة إلى تسجيل الدخول ←", "Back to sign in": "العودة إلى تسجيل الدخول", "Your own account. Your family's care space.": "حسابك الخاص، ومساحة رعاية أسرتك.",
    "Your child’s profile will be linked to your account.": "سيتم ربط ملف طفلك بحسابك.", "Your care workspace": "مساحة متابعة الرعاية", "Clinic workspace": "مساحة العيادة", "Family workspace": "مساحة الأسرة",
    "Child profiles": "ملفات الأطفال", "Clinic overview": "نظرة عامة للعيادة", "Parent dashboard": "لوحة ولي الأمر", "Manage profiles and follow the latest readings in one place.": "أدر الملفات وتابع أحدث القراءات في مكان واحد.",
    "Follow your child’s latest readings and keep their profile up to date.": "تابع أحدث قراءات طفلك وحدّث بيانات ملفه.", "Review children’s latest sensor status and clinic-configured alerts.": "راجع أحدث قراءات الأطفال والتنبيهات المحددة في العيادة.",
    "Children in your care": "الأطفال تحت رعايتك", "Registered profiles": "الملفات المسجلة", "Flagged readings": "قراءات تستدعي الانتباه", "Warning or critical status": "حالة تحذير أو حالة حرجة", "Profiles with readings": "ملفات بها قراءات", "Latest received data": "آخر بيانات مستلمة",
    "Profile details": "تفاصيل الملف", "Add a child": "إضافة طفل", "Add child": "إضافة طفل", "A few details to keep their profile up to date.": "بعض التفاصيل للحفاظ على تحديث الملف.", "Child ID": "معرّف الطفل",
    "Match the ID assigned to the child's monitoring device.": "طابق المعرّف المخصص لجهاز متابعة الطفل.", "Age": "العمر", "Height": "الطول", "Weight": "الوزن", "years": "سنوات", "cm": "سم", "kg": "كجم",
    "Save child profile": "حفظ ملف الطفل", "Update child profile": "تحديث ملف الطفل", "Cancel": "إلغاء", "Keep your account details private and your child's profile up to date.": "حافظ على خصوصية حسابك وحدّث ملف طفلك.",
    "People first": "الاهتمام بالإنسان أولًا", "Saved children": "الأطفال المسجلون", "A little more context for every reading.": "سياق أوضح لكل قراءة.", "Refresh": "تحديث", "Profiles will appear here": "ستظهر الملفات هنا", "Save a child profile to get started.": "احفظ ملف طفل للبدء.",
    "No child profiles found": "لا توجد ملفات أطفال", "Parent registrations will appear here.": "ستظهر تسجيلات أولياء الأمور هنا.", "No profiles yet": "لا توجد ملفات بعد", "Use Add child to register your first child.": "استخدم إضافة طفل لتسجيل أول طفل.",
    "Child": "الطفل", "Status": "الحالة", "Latest vitals": "أحدث القياسات", "Parent email": "بريد ولي الأمر", "Actions": "الإجراءات", "Edit": "تعديل", "Delete": "حذف", "Edit child profile": "تعديل ملف الطفل", "No parent email": "لا يوجد بريد لولي الأمر",
    "A closer look": "نظرة أقرب", "Live sensor readings": "قراءات أجهزة المتابعة", "The latest measurements received from your child's device.": "أحدث القياسات المستلمة من جهاز طفلك.", "Device readings": "قراءات الجهاز", "Child profile": "ملف الطفل", "Add a child profile first": "أضف ملف طفل أولًا",
    "Refresh readings": "تحديث القراءات", "Waiting for a child profile.": "في انتظار ملف طفل.", "Heart rate": "معدل ضربات القلب", "Oxygen · SpO₂": "الأكسجين · SpO₂", "Oxygen saturation": "تشبع الأكسجين", "% saturation": "% تشبع", "Temperature": "درجة الحرارة", "Respiratory rate": "معدل التنفس", "Activity": "النشاط", "Reported by the device": "كما يرسلها الجهاز", "bpm": "نبضة/دقيقة", "breaths / min": "نفس/دقيقة", "breaths/min": "نفس/دقيقة",
    "Bring the readings together.": "اجمع القراءات في تقرير.", "Create a report from the latest available data.": "أنشئ تقريرًا من أحدث البيانات المتاحة.", "Generate report from latest reading": "إنشاء تقرير من أحدث قراءة", "Generating report…": "جارٍ إنشاء التقرير…",
    "Readings are supplied by the monitoring device. “Not provided” means that measurement has not been received.": "يرسل جهاز المتابعة القراءات. تعني «غير متوفر» أن القياس لم يصل.",
    "Stay in the loop": "تابع المستجدات", "Recent parent alerts": "أحدث تنبيهات أولياء الأمور", "Recent alerts for your family": "أحدث تنبيهات أسرتك", "Updates and shared reports, kept together.": "المستجدات والتقارير المشتركة في مكان واحد.",
    "Clinic preferences": "تفضيلات العيادة", "Clinic alert thresholds": "حدود تنبيهات العيادة", "Set the limits your clinic uses to flag incoming measurements. Oxygen and temperature are checked even when other readings are missing. Alerts support clinical review and do not provide a diagnosis.": "حدد الحدود التي تستخدمها العيادة لتنبيه الفريق إلى القياسات. يُفحص الأكسجين والحرارة حتى عند غياب قراءات أخرى. تدعم التنبيهات المراجعة السريرية ولا تقدم تشخيصًا.",
    "Alert below SpO₂ (%)": "تنبيه عند انخفاض SpO₂ عن (%)", "Temperature warning (°C)": "حد تحذير الحرارة (°م)", "Temperature critical (°C)": "حد الحرارة الحرج (°م)", "Resting HR max, age 0–3": "أقصى نبض في الراحة، عمر 0–3", "Resting HR max, age over 3": "أقصى نبض في الراحة، أكبر من 3", "Respiratory rate max, age 0–3": "أقصى معدل تنفس، عمر 0–3", "Respiratory rate max, age over 3": "أقصى معدل تنفس، أكبر من 3", "Save clinic thresholds": "حفظ حدود العيادة", "Clinic thresholds saved.": "تم حفظ حدود العيادة.",
    "NEOCARE · Connected care, every day.": "NEOCARE · رعاية متصلة كل يوم.", "For information and clinical review.": "للمعلومات والمراجعة السريرية.", "Normal": "طبيعي", "Warning": "تحذير", "Critical": "حرج", "Unknown": "غير معروف", "Waiting for readings": "في انتظار القراءات", "Incomplete reading": "قراءة غير مكتملة", "Not provided": "غير متوفر", "Resting": "في راحة", "Sleeping": "نائم", "Active": "نشط", "No sensor reading": "لا توجد قراءة للجهاز",
    "Loading latest readings…": "جارٍ تحميل أحدث القراءات…", "Measurement time unavailable": "وقت القياس غير متاح", "Measurement time unavailable.": "وقت القياس غير متاح.", "Reading time unavailable": "وقت القراءة غير متاح", "Time unavailable": "الوقت غير متاح", "Add a child profile to view sensor readings.": "أضف ملف طفل لعرض القراءات.", "No sensor readings received yet for this child. Waiting for the ESP32.": "لم تصل قراءات لهذا الطفل بعد. في انتظار الجهاز.",
    "Generating recommendations from the latest reading.": "جارٍ إنشاء التوصيات من أحدث قراءة.", "Recommendation report": "تقرير التوصيات", "Print / Save as PDF": "طباعة / حفظ PDF", "Send PDF to parent": "إرسال التقرير إلى ولي الأمر", "Download recommendation PDF": "تنزيل تقرير التوصيات", "Assessment notes": "ملاحظات التقييم", "Local AI recommendations (Ollama)": "توصيات الذكاء الاصطناعي المحلي (Ollama)", "Rule-based recommendations": "توصيات مستندة إلى القواعد", "Immediate safety guidance": "إرشادات سلامة فورية", "Deterministic safety guidance": "إرشادات سلامة مستندة إلى القواعد", "Additional suggestions": "اقتراحات إضافية",
    "Report ready. Recommendations generated with local AI (Ollama).": "التقرير جاهز. تم إنشاء التوصيات محليًا باستخدام Ollama.", "Report ready. Rule-based recommendations are shown.": "التقرير جاهز. تُعرض توصيات مستندة إلى القواعد.", "Report ready. Urgent guidance is provided without waiting for AI.": "التقرير جاهز. تُعرض الإرشادات العاجلة دون انتظار الذكاء الاصطناعي.", "Urgent guidance is provided immediately without waiting for AI.": "تُقدم الإرشادات العاجلة فورًا دون انتظار الذكاء الاصطناعي.",
    "AI recommendations are generated locally with Ollama from de-identified readings and may be incorrect. They are not a diagnosis or medical advice. Follow deterministic safety guidance and consult a qualified pediatric clinician.": "تُنتج توصيات الذكاء الاصطناعي محليًا بواسطة Ollama من قراءات دون بيانات تعريف، وقد تكون غير صحيحة. ليست تشخيصًا أو نصيحة طبية. اتبع إرشادات السلامة واستشر طبيب أطفال مؤهلًا.",
    "Local recommendations are general guidance, not a medical diagnosis or medical advice. Follow deterministic safety guidance and consult a qualified pediatric clinician.": "التوصيات المحلية إرشادات عامة وليست تشخيصًا أو نصيحة طبية. اتبع إرشادات السلامة واستشر طبيب أطفال مؤهلًا.",
    "Local AI is unavailable. Start Ollama and make sure the configured model is downloaded. Showing rule-based guidance instead.": "الذكاء الاصطناعي المحلي غير متاح. شغّل Ollama وتأكد من تنزيل النموذج المحدد. تُعرض إرشادات القواعد بدلًا منه.",
    "No parent alerts have been recorded.": "لم تُسجل تنبيهات لأولياء الأمور بعد.", "Download report PDF": "تنزيل التقرير PDF", "Delete alert": "حذف التنبيه", "Alert deleted from the clinic and parent histories, including any saved PDF.": "تم حذف التنبيه من سجل العيادة وولي الأمر، بما في ذلك أي تقرير PDF محفوظ.", "Email delivered": "تم إرسال البريد الإلكتروني", "Email not delivered": "لم يُرسل البريد الإلكتروني", "Email pending": "البريد قيد الانتظار", "Saved in alert history": "محفوظ في سجل التنبيهات",
    "Child profile editing cancelled.": "تم إلغاء تعديل ملف الطفل.", "Profile edit cancelled.": "تم إلغاء تعديل الملف.", "Language": "اللغة", "Enter your clinic username": "أدخل اسم مستخدم العيادة", "Enter your email": "أدخل بريدك الإلكتروني", "Enter your password": "أدخل كلمة المرور", "Your full name": "اسمك الكامل", "Child's full name": "اسم الطفل الكامل",
    "Waiting for device readings": "في انتظار قراءات الجهاز", "Could not check device status": "تعذر التحقق من حالة القراءات", "No recent device readings": "لا توجد قراءات حديثة للجهاز", "Some measurements are missing": "بعض القياسات مفقودة", "Recent device readings received": "تم استلام قراءات حديثة للجهاز", "Try refreshing when the server connection is available.": "حاول التحديث عند توفر الاتصال بالخادم.", "Check the device connection and sensor placement.": "تحقق من اتصال الجهاز وموضع المستشعر.", "Readings will appear after the device sends a measurement.": "ستظهر القراءات بعد أن يرسل الجهاز قياسًا.", "All required measurements are available.": "جميع القياسات المطلوبة متوفرة.",
    "Reading history": "سجل القراءات", "Review recorded measurements over time. Missing values are not estimated.": "راجع القياسات المسجلة بمرور الوقت. لا تُقدّر القيم المفقودة.", "Time range": "الفترة الزمنية", "Last 24 hours": "آخر 24 ساعة", "Last 7 days": "آخر 7 أيام", "Measurement": "القياس", "Refresh history": "تحديث السجل", "Select a child to view history.": "اختر طفلًا لعرض السجل.", "Loading reading history…": "جارٍ تحميل سجل القراءات…", "No recorded measurements in this time range.": "لا توجد قياسات مسجلة في هذه الفترة.", "Points represent recorded measurements. Lines connect available readings.": "تمثل النقاط القياسات المسجلة، وتصل الخطوط بين القراءات المتاحة.", "View readings table": "عرض جدول القراءات", "Time": "الوقت",
    "New": "جديد", "Acknowledged": "تمت المراجعة", "Resolved": "تم الحل", "Review alert and clinical notes": "مراجعة التنبيه والملاحظات السريرية", "Alert status": "حالة التنبيه", "Internal clinical note": "ملاحظة سريرية داخلية", "Add context for the care team": "أضف معلومات لفريق الرعاية", "Save alert update": "حفظ تحديث التنبيه", "Alert updated.": "تم تحديث التنبيه.", "Clinician": "الطبيب",
    "Doctor accounts": "حسابات الأطباء", "Create an individual sign-in for each clinician so actions can be attributed to their account.": "أنشئ حسابًا مستقلًا لكل طبيب لتوثيق الإجراءات باسم صاحب الحساب.", "Display name": "الاسم الظاهر", "Create doctor account": "إنشاء حساب طبيب", "Individual doctor accounts": "حسابات الأطباء الفردية", "No individual doctor accounts have been created yet.": "لم تُنشأ حسابات أطباء فردية بعد.", "Doctor account created.": "تم إنشاء حساب الطبيب.", "Clinic activity log": "سجل نشاط العيادة", "Review recorded account, profile, alert, and settings changes.": "راجع التغييرات المسجلة للحسابات والملفات والتنبيهات والإعدادات.", "Refresh activity log": "تحديث سجل النشاط", "Actor": "المستخدم", "Action": "الإجراء", "Target": "العنصر", "Recent recorded changes": "أحدث التغييرات المسجلة", "No recorded activity yet.": "لا يوجد نشاط مسجل بعد.",
    "Doctor access required": "يلزم حساب طبيب", "Sign in required": "يلزم تسجيل الدخول", "Alert not found": "التنبيه غير موجود", "The request could not be completed.": "تعذر إكمال الطلب.", "Failed to fetch": "تعذر الاتصال بالخادم", "The PDF could not be generated.": "تعذر إنشاء ملف PDF.", "The alert PDF could not be downloaded.": "تعذر تنزيل تقرير التنبيه.",
    "profile.created": "إنشاء ملف", "profile.updated": "تحديث ملف", "profile.deleted": "حذف ملف", "alert.updated": "تحديث تنبيه", "alert.deleted": "حذف تنبيه", "doctor.created": "إنشاء حساب طبيب", "thresholds.updated": "تحديث الحدود", "report.sent": "إرسال تقرير"
  };
  let language = "en";
  try { if (localStorage.getItem("neocare-language") === "ar") language = "ar"; } catch {}
  const originals = new WeakMap();
  const attributeOriginals = new WeakMap();
  const ignored = "script,style,textarea,input,code,pre,[data-no-translate],[data-language]";
  const translate = (source) => {
    if (language !== "ar" || typeof source !== "string") return source;
    const text = source.trim();
    let translated = arabic[text];
    if (!translated) {
      const patterns = [
        [/^Last received (.+)$/, (_, date) => `آخر استلام ${date}`],
        [/^(Email delivered|Email not delivered|Email pending|Saved in alert history) · (.+)$/, (_, status, date) => `${arabic[status]} · ${date}`],
        [/^(Doctor|Parent) (.+)$/, (_, role, id) => `${role === "Doctor" ? "طبيب" : "ولي أمر"} ${id}`],
        [/^Reading not recent · Last received (.+)\. More than 5 minutes ago; check the device connection\.(.*)$/, (_, date, suffix) => `القراءة غير حديثة · آخر استلام ${date}. مضى أكثر من 5 دقائق؛ تحقق من اتصال الجهاز.${suffix}`],
        [/^Missing measurements: (.+)$/, (_, fields) => `القياسات المفقودة: ${fields.split(", ").map((field) => arabic[field] || field).join("، ")}`],
        [/^(\d+) recorded measurements\.( A subset of recorded measurements is shown\.)?$/, (_, count, rest) => `${count} قياسات مسجلة.${rest ? " تُعرض مجموعة فرعية من القياسات المسجلة." : ""}`],
        [/^(\d+) recorded measurements\. The same readings are available in the table below\.$/, (_, count) => `${count} قياسات مسجلة. تتوفر القراءات نفسها في الجدول أدناه.`],
        [/^(.+) history$/, (_, metric) => `سجل ${arabic[metric] || metric}`],
        [/^History could not be loaded: (.+)$/, (_, error) => `تعذر تحميل السجل: ${arabic[error] || error}`],
        [/^(Critical|Warning|Normal): (.+)$/, (_, status, name) => `${arabic[status]}: ${name}`],
        [/^Edit (.+)'s profile$/, (_, name) => `تعديل ملف ${name}`],
        [/^Delete (.+)'s profile$/, (_, name) => `حذف ملف ${name}`],
        [/^Delete alert for (.+)$/, (_, name) => `حذف تنبيه ${name}`],
        [/^Download (?:alert )?report for (.+)$/, (_, name) => `تنزيل تقرير ${name}`],
        [/^Print report for (.+)$/, (_, name) => `طباعة تقرير ${name}`],
        [/^Send (.+)'s report to their parent$/, (_, name) => `إرسال تقرير ${name} إلى ولي الأمر`],
        [/^(Child added|Profile saved): (.+)$/, (_, action, name) => `${action === "Child added" ? "تمت إضافة الطفل" : "تم حفظ الملف"}: ${name}`],
        [/^Profile deleted for (.+)\. Historical readings were kept\.$/, (_, name) => `تم حذف ملف ${name}. تم الاحتفاظ بالقراءات السابقة.`],
        [/^Delete this alert for (.+)\? This removes it from the clinic and parent alert histories and deletes any saved PDF\. This cannot be undone\.$/, (_, name) => `هل تريد حذف تنبيه ${name}؟ سيُحذف من سجل العيادة وولي الأمر مع أي ملف PDF محفوظ. لا يمكن التراجع عن ذلك.`],
        [/^Delete the profile for (.+)\? Historical monitoring data will be kept\.$/, (_, name) => `هل تريد حذف ملف ${name}؟ سيتم الاحتفاظ ببيانات المتابعة السابقة.`],
        [/^(.+) · Age (.+) · (.+)$/, (_, name, age, time) => `${name} · العمر ${age} · ${time}`],
        [/^(.+) (years|cm|kg|bpm|breaths\/min)$/, (_, value, unit) => `${value} ${arabic[unit] || unit}`]
      ];
      for (const [pattern, replacement] of patterns) if (pattern.test(text)) { translated = text.replace(pattern, replacement); break; }
    }
    if (!translated && text.includes(" Respiratory rate and activity are needed for the report.")) {
      translated = translate(text.replace(" Respiratory rate and activity are needed for the report.", "")) + " يلزم معدل التنفس والنشاط لإنشاء التقرير.";
    }
    return translated ? source.replace(text, translated) : source;
  };
  function translateText(node) {
    if (!node.parentElement || node.parentElement.closest(ignored)) return;
    const saved = originals.get(node);
    const source = saved && node.nodeValue === saved.rendered ? saved.source : node.nodeValue;
    const rendered = translate(source);
    originals.set(node, { source, rendered });
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }
  function translateAttributes(element) {
    if (element.closest("[data-no-translate],[data-language]") || ["SCRIPT", "STYLE"].includes(element.tagName)) return;
    const saved = attributeOriginals.get(element) || {};
    for (const name of ["aria-label", "placeholder", "title"]) {
      const value = element.getAttribute(name);
      if (value == null) continue;
      const source = saved[name] && saved[name].rendered === value ? saved[name].source : value;
      const rendered = translate(source);
      saved[name] = { source, rendered };
      if (value !== rendered) element.setAttribute(name, rendered);
    }
    attributeOriginals.set(element, saved);
  }
  function translateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE && root !== document.body) return;
    translateAttributes(root);
    root.querySelectorAll("[aria-label],[placeholder],[title]").forEach(translateAttributes);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) translateText(walker.currentNode);
  }
  function setLanguage(next) {
    language = next === "ar" ? "ar" : "en";
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
    document.title = language === "ar" ? "NEOCARE | رعاية متصلة" : "NEOCARE | Connected care";
    document.querySelectorAll("[data-language]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.language === language)));
    translateTree(document.body);
    try { localStorage.setItem("neocare-language", language); } catch {}
    document.dispatchEvent(new CustomEvent("neocare:languagechange", { detail: { language } }));
  }
  window.NEOCARE_I18N = { translate, setLanguage, getLanguage: () => language, locale: () => language === "ar" ? "ar-EG" : "en-GB" };
  new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === "characterData") translateText(change.target);
      else if (change.type === "attributes") translateAttributes(change.target);
      else change.addedNodes.forEach(translateTree);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["aria-label", "placeholder", "title"] });
  setLanguage(language);
})();
