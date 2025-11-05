(function(){
  // Reveal on scroll
  const els = document.querySelectorAll('.reveal-cmms-all-features');
  const io = new IntersectionObserver((entries)=>{
    entries.forEach(e=>{
      if(e.isIntersecting){
        e.target.classList.add('is-visible');
        io.unobserve(e.target);
      }
    });
  }, {threshold: .2});
  els.forEach(el=>io.observe(el));

  // Make keyboard Enter activate cards nicely
  document.querySelectorAll('.card-cmms-all-features').forEach(a=>{
    a.addEventListener('keydown',(ev)=>{
      if(ev.key === 'Enter' || ev.key === ' '){
        ev.preventDefault();
        a.click();
      }
    });
  });
})();

document.addEventListener("DOMContentLoaded", () => {
  const faqCards = document.querySelectorAll(".faq-card");

  faqCards.forEach(card => {
    const question = card.querySelector("h4");
    question.addEventListener("click", () => {
      // Collapse all other open cards
      faqCards.forEach(c => {
        if (c !== card) c.classList.remove("active");
      });
      // Toggle the clicked one
      card.classList.toggle("active");
    });
  });
});
document.addEventListener("DOMContentLoaded", () => {
  const track = document.querySelector(".testimonial-track");
  const slides = document.querySelectorAll(".testimonial-card");
  const prev = document.querySelector(".arrow.left");
  const next = document.querySelector(".arrow.right");

  let index = 0;
  const total = slides.length;

  function showSlide(i) {
    index = (i + total) % total;
    track.style.transform = `translateX(-${index * 100}%)`;
  }

  function nextSlide() { showSlide(index + 1); }
  function prevSlide() { showSlide(index - 1); }

  next.addEventListener("click", nextSlide);
  prev.addEventListener("click", prevSlide);

  // Auto slide every 5 seconds
  let autoSlide = setInterval(nextSlide, 5000);

  // Pause auto on hover
  document.querySelector(".testimonial-slider").addEventListener("mouseenter", () => clearInterval(autoSlide));
  document.querySelector(".testimonial-slider").addEventListener("mouseleave", () => autoSlide = setInterval(nextSlide, 5000));
});


(function(){
  const viewport = document.querySelector('.t-viewport');
  const track    = document.querySelector('.t-track');
  const prevBtn  = document.querySelector('.t-arrow.prev');
  const nextBtn  = document.querySelector('.t-arrow.next');

  let slides   = Array.from(track.children);
  let index    = 0;
  let isAnimating = false;
  const gapPx  = 24;
  const intervalMs = 4000;

  // Determine how many cards are visible (1 on mobile, 2 on desktop)
  function visibleCount(){
    return window.matchMedia('(max-width: 900px)').matches ? 1 : 2;
  }

  // Prepare infinite: clone first (visibleCount + 2) slides to the end
  function primeClones(){
    // remove old clones first
    Array.from(track.querySelectorAll('.t-clone')).forEach(n => n.remove());
    const vc = visibleCount();
    const cloneN = Math.min(slides.length, vc + 2);
    for(let i=0;i<cloneN;i++){
      const c = slides[i].cloneNode(true);
      c.classList.add('t-clone');
      track.appendChild(c);
    }
    slides = Array.from(track.children);
  }

  function cardWidth(){
    // card width + gap
    const vc = visibleCount();
    const vpW = viewport.clientWidth;
    if(vc === 1) return vpW; // 100%
    // (100% - gap)/2
    return (vpW - gapPx) / 2;
  }

  function goTo(newIndex, withTransition = true){
    if(isAnimating) return;
    isAnimating = true;

    const shift = -newIndex * (cardWidth() + gapPx);
    track.style.transition = withTransition ? 'transform .45s ease' : 'none';
    track.style.transform  = `translateX(${shift}px)`;

    track.addEventListener('transitionend', onDone, { once: true });
    if(!withTransition) isAnimating = false;

    function onDone(){
      // If we moved beyond the last real slide, snap back
      const vc = visibleCount();
      const maxRealIndex = document.querySelectorAll('.t-track > :not(.t-clone)').length - vc;
      if(newIndex > maxRealIndex){
        index = 0;
        const snap = -index * (cardWidth() + gapPx);
        track.style.transition = 'none';
        track.style.transform  = `translateX(${snap}px)`;
      } else {
        index = newIndex;
      }
      isAnimating = false;
    }
  }

  function next(){ goTo(index + 1); }
  function prev(){
    if(isAnimating) return;
    const vc = visibleCount();
    const realCount = document.querySelectorAll('.t-track > :not(.t-clone)').length;
    if(index === 0){
      // jump to the last visible start, then animate back one
      const maxStart = Math.max(0, realCount - vc);
      const jump = -maxStart * (cardWidth() + gapPx);
      track.style.transition = 'none';
      track.style.transform  = `translateX(${jump}px)`;
      index = maxStart;
      requestAnimationFrame(()=> requestAnimationFrame(()=> goTo(index - 1)));
    }else{
      goTo(index - 1);
    }
  }

  // Auto-play (pause on hover/focus)
  let timer = null;
  function start(){ stop(); timer = setInterval(next, intervalMs); }
  function stop(){ if(timer){ clearInterval(timer); timer = null; } }

  viewport.addEventListener('mouseenter', stop);
  viewport.addEventListener('mouseleave', start);
  viewport.addEventListener('focusin', stop);
  viewport.addEventListener('focusout', start);

  nextBtn.addEventListener('click', next);
  prevBtn.addEventListener('click', prev);
  window.addEventListener('resize', ()=>{
    // Re-prime on layout change
    primeClones();
    goTo(index, false);
  });

  // Init
  primeClones();
  goTo(0, false);
  start();
})();
