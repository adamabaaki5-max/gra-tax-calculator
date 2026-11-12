(function () {
  /* Bulk Calculation form: the button caption follows the option chosen */
  var form = document.getElementById('bulk-form');
  if (!form) { return; }
  var btn = document.getElementById('bulk-btn');
  var sync = function () {
    var mode = form.querySelector('input[name="mode"]:checked');
    if (mode) { btn.textContent = mode.dataset.label; }
  };
  form.addEventListener('change', function (e) { if (e.target.name === 'mode') { sync(); } });
  sync();
})();
