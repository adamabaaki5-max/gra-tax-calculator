(function () {
  var num = function (v) { var n = parseFloat(String(v).replace(/,/g, '')); return isFinite(n) ? n : null; };
  var r2 = function (n) { return Math.round(n * 100) / 100; };
  var fmt = function (n) { return n === null ? '' : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };

  /* work out the printed-table columns from the chargeable income and rate in each row */
  function recalc(table) {
    var cum = 0, tax = 0, ok = true;
    var rows = table.querySelectorAll('tbody tr');
    rows.forEach(function (tr, i) {
      var last = i === rows.length - 1;
      tr.querySelector('.lab').textContent = i === 0 ? 'First' : (last ? 'Exceeding' : 'Next');
      var rm = tr.querySelector('.rm');
      if (rm) { rm.style.visibility = last ? 'hidden' : 'visible'; }
      var wEl = tr.querySelector('.w');
      var w = wEl ? num(wEl.value) : null, r = num(tr.querySelector('.r').value);
      var pay = tr.querySelector('.pay'), c = tr.querySelector('.cum'), ct = tr.querySelector('.ctax');
      if (last || !ok || w === null || r === null) { pay.textContent = c.textContent = ct.textContent = ''; if (!last) { ok = false; } return; }
      var p = r2(w * r / 100);
      tax = r2(tax + p); cum = r2(cum + w);
      pay.textContent = fmt(p); c.textContent = fmt(cum); ct.textContent = fmt(tax);
    });
  }

  document.querySelectorAll('.band-table').forEach(function (table) {
    recalc(table);
    table.addEventListener('input', function (e) { e.target.classList.remove('flag'); recalc(table); });
    table.addEventListener('click', function (e) {
      if (e.target.classList.contains('rm')) { e.target.closest('tr').remove(); recalc(table); }
    });
  });

  document.querySelectorAll('.add-band').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var key = btn.dataset.key;
      var table = document.querySelector('.band-table[data-key="' + key + '"]');
      var tbody = table.querySelector('tbody');
      var row = document.getElementById('tpl-' + key).content.firstElementChild.cloneNode(true);
      tbody.insertBefore(row, tbody.lastElementChild);       // new bands go just before "Exceeding"
      recalc(table);
      row.querySelector('.w').focus();
    });
  });
})();
