(function () {
  const tabButtons = document.querySelectorAll('.tab-about-ieng-mission');
  const panels = document.querySelectorAll('.content-about-ieng-mission');

  function showPanel(targetSelector) {
    panels.forEach(p => {
      const isTarget = '#' + p.id === targetSelector;
      p.toggleAttribute('hidden', !isTarget);
      p.classList.toggle('is-visible-about-ieng-mission', isTarget);
    });
  }

  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      // activate pill
      tabButtons.forEach(b => {
        b.classList.remove('is-active-about-ieng-mission');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('is-active-about-ieng-mission');
      btn.setAttribute('aria-selected', 'true');

      // switch content
      const target = btn.getAttribute('data-target');
      showPanel(target);
    });
  });

  // default visible (Mission)
  showPanel('#mission-about-ieng-mission');
})();
// Enable flip on tap for touch devices
  document.querySelectorAll('.card-meet-ieng-about').forEach(card => {
    let tapped = false;
    card.addEventListener('click', () => {
      // toggle focus to trigger the same CSS flip used on :hover/:focus
      if (!tapped) {
        tapped = true;
        card.focus();
        setTimeout(()=> tapped=false, 500);
      } else {
        // second tap follows any primary link if you add one later
        card.blur();
      }
    });
  });