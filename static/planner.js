(function () {
  var input = document.getElementById('csv_file');
  var drop = document.getElementById('drop');
  var text = document.getElementById('drop_text');
  if (!input || !drop || !text) { return; }
  var original = text.textContent;
  input.addEventListener('change', function () {
    text.textContent = input.files && input.files.length ? input.files[0].name : original;
  });
  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function () { drop.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    drop.addEventListener(ev, function () { drop.classList.remove('over'); });
  });
})();
