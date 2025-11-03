
function showDay(dayId) {
  const allDays = document.querySelectorAll('.event-day');
  const tabs = document.querySelectorAll('.event-tab');

  allDays.forEach(d => d.style.display = 'none');
  tabs.forEach(t => t.classList.remove('active'));

  document.getElementById(dayId).style.display = 'block';
  event.target.classList.add('active');
}
document.getElementById('cmms-contact-form-getstarted').addEventListener('submit', function(event) {
    event.preventDefault(); // Prevents the page from refreshing

    const emailField = document.getElementById('email');
    const errorMsg = document.getElementById('error-msg');
    const loadingMsg = document.getElementById('loading-msg');
    const thankYouMsg = document.getElementById('thank-you-msg');
    const submitButton = document.getElementById('get-started-btn');

    // Check if the email is valid
    if (!emailField.value.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) {
        errorMsg.style.display = 'block';
        return;
    }

    // Hide error and show loading message
    errorMsg.style.display = 'none';
    loadingMsg.style.display = 'block';
    submitButton.disabled = true;

    // Create form data
    const formData = new FormData(this);

    // Send the AJAX request
    fetch("{% url 'cmmsApp:contact_section' %}", {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        // On success, show thank you message
        if (data.status === 'success') {
            loadingMsg.style.display = 'none';
            thankYouMsg.style.display = 'block';
            submitButton.disabled = false;

            // Clear form fields after submission
            emailField.value = '';
        }
    })
    .catch(error => {
        console.error('Error submitting form:', error);
        loadingMsg.style.display = 'none';
        submitButton.disabled = false;
        alert('Something went wrong. Please try again.');
    });
});


        /* IntersectionObserver reveal — shows elements when they enter the viewport,
           hides them again when they leave (works on scroll down and up). */
        (function () {
            const els = document.querySelectorAll('.reveal-mobility');
            if (!('IntersectionObserver' in window) || !els.length) {
                els.forEach(el => el.classList.add('is-visible-mobility'));
                return;
            }

            const io = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-visible-mobility');
                    } else {
                        entry.target.classList.remove('is-visible-mobility');
                    }
                });
            }, { threshold: 0.18 });

            els.forEach(el => io.observe(el));
        })();
 