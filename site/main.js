/* Fieldcraft landing — three small behaviours, nothing more.
   Scroll reveals, a nav that gains a background once you leave the hero, and a
   mobile menu. All of it degrades to a perfectly usable page if JS never runs. */
(function () {
  'use strict';

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- scroll reveal ---- */
  var items = document.querySelectorAll('.reveal');
  if (reduced || !('IntersectionObserver' in window)) {
    items.forEach(function (el) { el.classList.add('in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.06 });
    items.forEach(function (el) { io.observe(el); });
    // Belt and braces: whatever is still hidden after two seconds gets shown.
    // A reveal that never fires is a blank page, which is worse than no animation.
    setTimeout(function () {
      items.forEach(function (el) { el.classList.add('in'); });
    }, 2000);
  }

  /* ---- nav background past the hero ---- */
  var nav = document.getElementById('nav');
  var onScroll = function () { nav.classList.toggle('stuck', window.scrollY > 24); };
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  /* ---- mobile menu ---- */
  var burger = document.getElementById('burger');
  var menu = document.getElementById('mobileMenu');
  function setMenu(open) {
    menu.classList.toggle('open', open);
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  burger.addEventListener('click', function () {
    setMenu(burger.getAttribute('aria-expanded') !== 'true');
  });
  menu.addEventListener('click', function (e) {
    if (e.target.tagName === 'A') setMenu(false);
  });
  // A resize past the breakpoint should not leave the panel stranded open.
  window.addEventListener('resize', function () {
    if (window.innerWidth > 980) setMenu(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') setMenu(false);
  });
})();
