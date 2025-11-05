/*=============== SHOW MENU ===============*/
const showMenu = (toggleId, navId) => {
  const toggle = document.getElementById(toggleId),
        nav = document.getElementById(navId);

  if (!toggle || !nav) return;

  const MOBILE_BP = 1118;
  const isMobile = () => window.matchMedia(`(max-width:${MOBILE_BP}px)`).matches;

  // Open/close drawer
  toggle.addEventListener('click', () => {
    const opening = !nav.classList.contains('show-menu');
    nav.classList.toggle('show-menu');
    toggle.classList.toggle('show-icon');

    // When opening on mobile, ensure ALL dropdowns are collapsed
    if (opening && isMobile()) {
      document.querySelectorAll('.dropdown__item.active, .dropdown__subitem.active')
        .forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav__list > .dropdown__item > .nav__link')
        .forEach(l => l.setAttribute('aria-expanded', 'false'));
    }
  });

  // Top-level dropdowns (Solutions, Industries, etc.)
  document.querySelectorAll('.nav__list > .dropdown__item > .nav__link').forEach(link => {
    const item = link.closest('.dropdown__item');
    link.setAttribute('aria-expanded', 'false');

    link.addEventListener('click', (e) => {
      if (!isMobile()) return;              // desktop: normal hover/nav
      e.preventDefault();

      const willOpen = !item.classList.contains('active');

      // Close any other open top-level dropdowns
      document.querySelectorAll('.nav__list > .dropdown__item.active').forEach(openItem => {
        if (openItem !== item) openItem.classList.remove('active');
      });
      document.querySelectorAll('.nav__list > .dropdown__item > .nav__link')
        .forEach(l => l.setAttribute('aria-expanded', 'false'));

      // Toggle this one
      if (willOpen) {
        item.classList.add('active');
        link.setAttribute('aria-expanded', 'true');
      } else {
        item.classList.remove('active');
      }
    });
  });

  // Optional: nested submenus behave like accordion too
  document.querySelectorAll('.dropdown__subitem > .dropdown__link').forEach(sublink => {
    const subitem = sublink.closest('.dropdown__subitem');
    sublink.addEventListener('click', (e) => {
      if (!isMobile()) return;
      const hasSub = subitem.querySelector(':scope > .dropdown__submenu');
      if (hasSub) {
        e.preventDefault();
        // Close siblings
        subitem.parentElement.querySelectorAll('.dropdown__subitem.active')
          .forEach(s => { if (s !== subitem) s.classList.remove('active'); });
        subitem.classList.toggle('active');
      }
    });
  });

  // Close all when tapping outside the drawer (mobile only)
  document.addEventListener('click', (e) => {
    if (!isMobile()) return;
    const menu = document.getElementById('nav-menu');
    const toggleBtn = document.getElementById('nav-toggle');
    if (!menu.contains(e.target) && !toggleBtn.contains(e.target)) {
      menu.classList.remove('show-menu');
      toggleBtn.classList.remove('show-icon');
      document.querySelectorAll('.dropdown__item.active, .dropdown__subitem.active')
        .forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav__list > .dropdown__item > .nav__link')
        .forEach(l => l.setAttribute('aria-expanded', 'false'));
    }
  });

  // Reset state when resizing up to desktop
  window.addEventListener('resize', () => {
    if (!isMobile()) {
      document.querySelectorAll('.dropdown__item.active, .dropdown__subitem.active')
        .forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav__list > .dropdown__item > .nav__link')
        .forEach(l => l.setAttribute('aria-expanded', 'false'));
    }
  });
};
// Ensure sub-dropdowns (if any) expand with accordion behavior on mobile
document.addEventListener('DOMContentLoaded', () => {
  const MOBILE_BP = 1118;
  const isMobile = () => window.matchMedia(`(max-width:${MOBILE_BP}px)`).matches;

  // Top-level already handled; this is for nested .dropdown__subitem blocks
  document.querySelectorAll('.dropdown__subitem > .dropdown__link').forEach(sublink => {
    const subitem = sublink.closest('.dropdown__subitem');
    const submenu = subitem && subitem.querySelector(':scope > .dropdown__submenu');

    if (!submenu) return;

    sublink.addEventListener('click', (e) => {
      if (!isMobile()) return;      // desktop: keep hover behavior
      e.preventDefault();

      // Close sibling subitems
      const siblings = subitem.parentElement.querySelectorAll('.dropdown__subitem.active');
      siblings.forEach(s => { if (s !== subitem) s.classList.remove('active'); });

      // Toggle this subitem
      subitem.classList.toggle('active');
    });
  });
});

document.addEventListener('DOMContentLoaded', () => {
  showMenu('nav-toggle', 'nav-menu');
});
