/**
 * Minimal bilingual switch shared by every page.
 *
 * Markup carries both languages: <span data-ar="مرحبا" data-en="Hello"></span>.
 * Inputs use data-ar-placeholder / data-en-placeholder. Calling applyLang()
 * swaps text, direction, and the toggle's own label, and remembers the choice.
 */
(function (global) {
  var STORAGE_KEY = 'eilajipay.lang';

  function stored() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }

  function remember(lang) {
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* private mode */ }
  }

  function applyLang(lang, root) {
    var scope = root || document;
    var isAr = lang === 'ar';

    document.documentElement.lang = isAr ? 'ar' : 'en';
    document.documentElement.dir = isAr ? 'rtl' : 'ltr';

    scope.querySelectorAll('[data-ar]').forEach(function (el) {
      var text = isAr ? el.getAttribute('data-ar') : el.getAttribute('data-en');
      if (text != null) el.textContent = text;
    });

    scope.querySelectorAll('[data-ar-placeholder]').forEach(function (el) {
      var text = isAr ? el.getAttribute('data-ar-placeholder') : el.getAttribute('data-en-placeholder');
      if (text != null) el.placeholder = text;
    });

    scope.querySelectorAll('[data-lang-toggle]').forEach(function (el) {
      el.textContent = isAr ? 'EN' : 'العربية';
    });

    remember(lang);
    global.currentLang = lang;
    document.dispatchEvent(new CustomEvent('langchange', { detail: { lang: lang } }));
  }

  function initLang(defaultLang) {
    var lang = stored() || defaultLang || 'ar';
    applyLang(lang);
    document.querySelectorAll('[data-lang-toggle]').forEach(function (el) {
      el.addEventListener('click', function () {
        applyLang(global.currentLang === 'ar' ? 'en' : 'ar');
      });
    });
    return lang;
  }

  /** Arabic-Indic digits, so prices read naturally in the Arabic view. */
  function localeNum(value, lang) {
    var text = String(value);
    if (lang !== 'ar') return text;
    return text.replace(/[0-9]/g, function (d) { return '٠١٢٣٤٥٦٧٨٩'[Number(d)]; });
  }

  global.applyLang = applyLang;
  global.initLang = initLang;
  global.localeNum = localeNum;
  global.currentLang = 'ar';
})(window);
