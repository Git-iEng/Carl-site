// --- Tabs: FIX showDay so it does not use global 'event' ---
function showDay(dayId, evt) {
  const allDays = document.querySelectorAll('.event-day');
  const tabs = document.querySelectorAll('.event-tab');

  allDays.forEach(d => d.style.display = 'none');
  tabs.forEach(t => t.classList.remove('active'));

  const panel = document.getElementById(dayId);
  if (panel) panel.style.display = 'block';

  if (evt && evt.currentTarget) {
    evt.currentTarget.classList.add('active');
  }
}

// --- Get Started form AJAX submit ---
document.getElementById('cmms-contact-form-getstarted')?.addEventListener('submit', function (e) {
  e.preventDefault();

  const form = this;
  const postUrl = form.dataset.postUrl || form.action;
  if (!postUrl) {
    alert('Post URL missing. Please set data-post-url on the form.');
    return;
  }

  const emailField = document.getElementById('email');
  const errorMsg = document.getElementById('error-msg');
  const loadingMsg = document.getElementById('loading-msg');
  const thankYouMsg = document.getElementById('thank-you-msg');
  const submitButton = document.getElementById('get-started-btn');

  if (!emailField || !submitButton) return;

  const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((emailField.value || '').trim());
  if (!valid) {
    if (errorMsg) errorMsg.style.display = 'block';
    return;
  }

  if (errorMsg) errorMsg.style.display = 'none';
  if (thankYouMsg) thankYouMsg.style.display = 'none';
  if (loadingMsg) loadingMsg.style.display = 'block';

  submitButton.disabled = true;
  submitButton.classList.add('is-loading'); // optional (if you style it)

  const formData = new FormData(form);

  fetch(postUrl, {
    method: 'POST',
    body: formData,
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin'
  })
    .then(async (res) => {
      const ct = (res.headers.get('content-type') || '').toLowerCase();
      const data = ct.includes('application/json') ? await res.json() : null;

      if (!res.ok || !data) throw new Error('Bad response / not JSON');

      if (data.status === 'success' || data.ok === true) {
        if (loadingMsg) loadingMsg.style.display = 'none';
        if (thankYouMsg) thankYouMsg.style.display = 'block';
        form.reset();
      } else {
        if (loadingMsg) loadingMsg.style.display = 'none';
        alert(data.message || 'Submission failed. Please try again.');
      }
    })
    .catch((err) => {
      console.error('Error submitting form:', err);
      if (loadingMsg) loadingMsg.style.display = 'none';
      alert('Something went wrong. Please try again.');
    })
    .finally(() => {
      submitButton.disabled = false;
      submitButton.classList.remove('is-loading');
    });
});

// --- Reveal observer (unchanged) ---
(function () {
  const els = document.querySelectorAll('.reveal-mobility');
  if (!('IntersectionObserver' in window) || !els.length) {
    els.forEach(el => el.classList.add('is-visible-mobility'));
    return;
  }

  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) entry.target.classList.add('is-visible-mobility');
      else entry.target.classList.remove('is-visible-mobility');
    });
  }, { threshold: 0.18 });

  els.forEach(el => io.observe(el));
})();
