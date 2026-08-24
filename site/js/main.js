// Mobile nav toggle
(function () {
  var toggle = document.querySelector('.nav__toggle');
  var links = document.querySelector('.nav__links');
  if (!toggle || !links) return;
  toggle.addEventListener('click', function () {
    var open = links.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  // Close the menu when a link is tapped (mobile)
  links.addEventListener('click', function (e) {
    if (e.target.tagName === 'A') links.classList.remove('is-open');
  });
})();
