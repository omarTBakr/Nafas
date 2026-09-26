import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import type { Unavailable } from "./api";

export type Lang = "ar" | "en";

const STRINGS = {
  ar: {
    brand: "نَفَس",
    tagline: "احجز مع طبيبك بالدقيقة، واسأل مساعدك في أي وقت",
    findDoctor: "اختر طبيبًا",
    allSpecializations: "كل التخصصات",
    book: "احجز موعدًا",
    login: "تسجيل الدخول",
    logout: "خروج",
    register: "حساب جديد",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    passwordHint: "١٢ حرفًا على الأقل",
    fullName: "الاسم بالكامل",
    phone: "الموبايل (اختياري)",
    preferredLanguage: "لغة التواصل",
    haveAccount: "عندك حساب؟",
    noAccount: "ليس لديك حساب؟",
    myAppointments: "مواعيدي",
    doctors: "الأطباء",
    schedule: "جدول المواعيد",
    today: "اليوم",
    thisWeek: "هذا الأسبوع",
    pickDay: "اختر اليوم",
    freeTimes: "المواعيد المتاحة",
    noFreeTimes: "لا توجد مواعيد متاحة في هذا اليوم",
    exactTime: "أو اكتب وقتًا محددًا",
    check: "تحقق",
    reasonForVisit: "سبب الزيارة (اختياري)",
    holdTitle: "الموعد محجوز لك مؤقتًا",
    holdExpires: "أكّد خلال",
    confirm: "تأكيد الحجز",
    cancel: "إلغاء",
    cancelAppointment: "إلغاء الموعد",
    confirmed: "تم تأكيد موعدك",
    nearest: "أقرب المواعيد المتاحة:",
    noAppointments: "لا توجد مواعيد بعد",
    status_held: "بانتظار التأكيد",
    status_confirmed: "مؤكد",
    status_cancelled: "ملغى",
    status_completed: "تم",
    status_no_show: "لم يحضر",
    pendingPatient: "حجز مؤقت",
    clinicTime: "كل المواعيد بتوقيت العيادة",
    minutes: "دقيقة",
    loading: "جارٍ التحميل…",
    error: "حدث خطأ، حاول مرة أخرى",
    wrongLogin: "البريد أو كلمة المرور غير صحيحة",
    emailTaken: "يوجد حساب بهذا البريد بالفعل",
    invalidEmail: "هذا البريد غير صالح، تأكد منه",
    invalidPassword: "كلمة المرور يجب أن تكون ١٢ حرفًا على الأقل",
    invalidForm: "راجع البيانات المكتوبة",
    back: "رجوع",
    inPerson: "في العيادة",
    online: "أونلاين",
    profile: "ملفي",
    dialect: "لهجتك",
    dialectHint: "المساعد يتكلم ويكتب لك بلهجتك",
    chooseDialect: "اختر لهجتك",
    voice: "صوت المساعد",
    voiceAny: "بدون تفضيل",
    voice_female: "صوت نسائي",
    voice_male: "صوت رجالي",
    save: "حفظ",
    saved: "تم الحفظ",
    dialect_eg: "مصري",
    dialect_sa: "سعودي",
    dialect_ma: "مغربي",
    dialect_bh: "بحريني",
    dialect_sd: "سوداني",
    dialect_iq: "عراقي",
    dialect_lb: "لبناني",
    dialect_sy: "سوري",
    dialect_ly: "ليبي",
    dialect_ps: "فلسطيني",
    dialect_tn: "تونسي",
    dialect_dz: "جزائري",
    dialect_ye: "يمني",
    reason_not_whole_minute: "اختر وقتًا بالدقيقة",
    reason_too_soon: "هذا الوقت قريب جدًا، اختر وقتًا لاحقًا",
    reason_beyond_horizon: "هذا الوقت بعيد جدًا عن جدول الحجز",
    reason_outside_hours: "الطبيب لا يستقبل في هذا الوقت",
    reason_wrong_mode: "هذا الوقت لنوع زيارة آخر",
    reason_time_off: "الطبيب في إجازة في هذا الوقت",
    reason_taken: "هذا الوقت محجوز",
    reason_not_bookable: "هذا الطبيب لا يستقبل حجوزات بعد",
    reason_hold_expired: "انتهت مهلة الحجز المؤقت، اختر الوقت مرة أخرى",
    reason_invalid_transition: "لا يمكن تنفيذ هذا على هذا الموعد",
    tabSlots: "اختيار الموعد",
    tabChat: "اسأل المساعد",
    chatIntro: "اكتب للمساعد بطريقتك: «بكرة بعد العصر» أو «الأربعاء ٥:٤٠»",
    aiLabel: "مساعد آلي، مش دكتور",
    you: "أنت",
    assistant: "المساعد",
    doctorReply: "رد الدكتور",
    typing: "المساعد بيكتب…",
    send: "إرسال",
    messagePlaceholder: "اكتب رسالتك",
    chatUnavailable: "المساعد غير متاح الآن، جرّب بعد قليل أو استخدم اختيار الموعد",
    heldInChat: "محجوز لك مؤقتًا",
    confirmedInChat: "تم التأكيد",
    cancelledInChat: "تم الإلغاء",
    notifications: "الإشعارات",
    noNotifications: "لا توجد إشعارات",
    markRead: "تم",
    notice_confirmed: "تم تأكيد موعدك",
    notice_hold_expired: "انتهت مهلة الحجز المؤقت ولم يتم التأكيد",
    notice_reminder: "تذكير بموعدك",
    notice_cancelled_by_doctor: "الطبيب ألغى موعدك",
    markNoShow: "لم يحضر",
    record: "سجّل رسالة صوتية",
    stopRecording: "إيقاف وإرسال",
    recording: "جارٍ التسجيل…",
    voiceNote: "رسالة صوتية",
    micDenied: "مش قادرين نوصل للميكروفون، اسمح بيه من إعدادات المتصفح",
    suggestedDialect: "يبدو إنك بتكتب باللهجة",
    useSuggestion: "استخدمها",
  },
  en: {
    brand: "Nafas",
    tagline: "Book your doctor to the minute, and ask your assistant any time",
    findDoctor: "Choose a doctor",
    allSpecializations: "All specializations",
    book: "Book an appointment",
    login: "Log in",
    logout: "Log out",
    register: "Sign up",
    email: "Email",
    password: "Password",
    passwordHint: "At least 12 characters",
    fullName: "Full name",
    phone: "Mobile (optional)",
    preferredLanguage: "Preferred language",
    haveAccount: "Have an account?",
    noAccount: "No account yet?",
    myAppointments: "My appointments",
    doctors: "Doctors",
    schedule: "Schedule",
    today: "Today",
    thisWeek: "This week",
    pickDay: "Pick a day",
    freeTimes: "Free times",
    noFreeTimes: "No free times on this day",
    exactTime: "Or type an exact time",
    check: "Check",
    reasonForVisit: "Reason for the visit (optional)",
    holdTitle: "This time is held for you",
    holdExpires: "Confirm within",
    confirm: "Confirm booking",
    cancel: "Cancel",
    cancelAppointment: "Cancel appointment",
    confirmed: "Your appointment is confirmed",
    nearest: "Nearest free times:",
    noAppointments: "No appointments yet",
    status_held: "Awaiting confirmation",
    status_confirmed: "Confirmed",
    status_cancelled: "Cancelled",
    status_completed: "Done",
    status_no_show: "No-show",
    pendingPatient: "Pending hold",
    clinicTime: "All times are clinic time",
    minutes: "min",
    loading: "Loading…",
    error: "Something went wrong, please try again",
    wrongLogin: "Email or password is wrong",
    emailTaken: "An account with this email already exists",
    invalidEmail: "That email address is not valid; please check it",
    invalidPassword: "The password needs at least 12 characters",
    invalidForm: "Please check what you entered",
    back: "Back",
    inPerson: "In person",
    online: "Online",
    profile: "Profile",
    dialect: "Your dialect",
    dialectHint: "The assistant speaks and writes to you in your dialect",
    chooseDialect: "Choose your dialect",
    voice: "Assistant voice",
    voiceAny: "No preference",
    voice_female: "Female voice",
    voice_male: "Male voice",
    save: "Save",
    saved: "Saved",
    dialect_eg: "Egyptian",
    dialect_sa: "Saudi",
    dialect_ma: "Moroccan",
    dialect_bh: "Bahraini",
    dialect_sd: "Sudanese",
    dialect_iq: "Iraqi",
    dialect_lb: "Lebanese",
    dialect_sy: "Syrian",
    dialect_ly: "Libyan",
    dialect_ps: "Palestinian",
    dialect_tn: "Tunisian",
    dialect_dz: "Algerian",
    dialect_ye: "Yemeni",
    reason_not_whole_minute: "Pick a whole minute",
    reason_too_soon: "That is too soon; pick a later time",
    reason_beyond_horizon: "That is too far ahead to book",
    reason_outside_hours: "The doctor is not seeing patients then",
    reason_wrong_mode: "That time is for another kind of visit",
    reason_time_off: "The doctor is away then",
    reason_taken: "That time is taken",
    reason_not_bookable: "This doctor is not taking bookings yet",
    reason_hold_expired: "The hold ran out; please pick the time again",
    reason_invalid_transition: "That cannot be done to this appointment",
    tabSlots: "Pick a time",
    tabChat: "Ask the assistant",
    chatIntro: "Write to the assistant your own way: \"tomorrow afternoon\" or \"Wednesday 5:40\"",
    aiLabel: "AI assistant, not a doctor",
    you: "You",
    assistant: "Assistant",
    doctorReply: "Doctor's reply",
    typing: "The assistant is typing…",
    send: "Send",
    messagePlaceholder: "Type your message",
    chatUnavailable: "The assistant is unavailable right now; try again shortly or pick a time instead",
    heldInChat: "Held for you",
    confirmedInChat: "Confirmed",
    cancelledInChat: "Cancelled",
    notifications: "Notifications",
    noNotifications: "No notifications",
    markRead: "Done",
    notice_confirmed: "Your appointment is confirmed",
    notice_hold_expired: "Your held time ran out before it was confirmed",
    notice_reminder: "Reminder of your appointment",
    notice_cancelled_by_doctor: "The doctor cancelled your appointment",
    markNoShow: "No-show",
    record: "Record a voice note",
    stopRecording: "Stop and send",
    recording: "Recording…",
    voiceNote: "Voice note",
    micDenied: "The microphone is not available; allow it in the browser's settings",
    suggestedDialect: "You seem to write in",
    useSuggestion: "Use it",
  },
} as const;

export type Key = keyof (typeof STRINGS)["en"];

interface I18n {
  lang: Lang;
  locale: string;
  t: (key: Key) => string;
  reason: (reason: Unavailable | undefined | null) => string;
  setLang: (lang: Lang) => void;
}

const I18nContext = createContext<I18n | null>(null);

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("nafas.lang");
    if (saved === "ar" || saved === "en") return saved;
  } catch {
    // storage can be unavailable (private windows); fall through to Arabic
  }
  return "ar";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem("nafas.lang", next);
    } catch {
      // not remembered, but still switched
    }
  }, []);

  const t = useCallback((key: Key) => STRINGS[lang][key] ?? STRINGS.en[key], [lang]);
  const reason = useCallback(
    (r: Unavailable | undefined | null) => (r ? t(`reason_${r}` as Key) : t("error")),
    [t],
  );

  // Arabic digits and month names for Arabic; the Egyptian locale keeps Latin
  // separators readable next to Arabic text
  const locale = lang === "ar" ? "ar-EG" : "en-GB";

  return <I18nContext.Provider value={{ lang, locale, t, reason, setLang }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n outside I18nProvider");
  return context;
}
