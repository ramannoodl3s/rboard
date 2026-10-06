/* @ds-bundle: {"format":4,"namespace":"Softclub","components":[]} */
(function () {
  // 16px grid, 1.5px stroke, round caps and joins, drawn in currentColor.
  var icons = {
  "select": "<path d=\"M3 2.5 12.5 7 8.2 8.2 6.8 12.5z\"/>",
  "pan": "<path d=\"M8 2v12M2 8h12M8 2 6.3 3.7M8 2l1.7 1.7M8 14l-1.7-1.7M8 14l1.7-1.7M2 8l1.7-1.7M2 8l1.7 1.7M14 8l-1.7-1.7M14 8l-1.7 1.7\"/>",
  "zoom": "<circle cx=\"7\" cy=\"7\" r=\"4.25\"/><path d=\"M10.2 10.2 13.5 13.5\"/>",
  "crop": "<path d=\"M4.5 1.5v9a1 1 0 0 0 1 1h9M1.5 4.5h9a1 1 0 0 1 1 1v9\"/>",
  "flip-h": "<path d=\"M8 1.5v13\"/><path d=\"M6 4.5v7H2z\"/><path d=\"M10 4.5v7h4z\"/>",
  "flip-v": "<path d=\"M1.5 8h13\"/><path d=\"M4.5 6h7V2z\"/><path d=\"M4.5 10h7v4z\"/>",
  "grayscale": "<circle cx=\"8\" cy=\"8\" r=\"5.5\"/><path d=\"M8 2.5a5.5 5.5 0 0 1 0 11z\" fill=\"currentColor\"/>",
  "text": "<path d=\"M3 4h10M8 4v9M6 13h4\"/>",
  "lock": "<rect x=\"3.5\" y=\"7\" width=\"9\" height=\"6.5\" rx=\"1.5\"/><path d=\"M5.5 7V5a2.5 2.5 0 0 1 5 0v2\"/>",
  "eye": "<path d=\"M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z\"/><circle cx=\"8\" cy=\"8\" r=\"1.8\"/>",
  "grid": "<rect x=\"2.5\" y=\"2.5\" width=\"4.5\" height=\"4.5\" rx=\"1\"/><rect x=\"9\" y=\"2.5\" width=\"4.5\" height=\"4.5\" rx=\"1\"/><rect x=\"2.5\" y=\"9\" width=\"4.5\" height=\"4.5\" rx=\"1\"/><rect x=\"9\" y=\"9\" width=\"4.5\" height=\"4.5\" rx=\"1\"/>",
  "layers": "<path d=\"M8 2 14 5.5 8 9 2 5.5z\"/><path d=\"M2 8.5 8 12l6-3.5\"/>",
  "plus": "<path d=\"M8 3v10M3 8h10\"/>",
  "minus": "<path d=\"M3 8h10\"/>",
  "close": "<path d=\"M3.5 3.5l9 9M12.5 3.5l-9 9\"/>",
  "check": "<path d=\"M3 8.5 6.5 12 13 4.5\"/>",
  "chevron-down": "<path d=\"M4 6l4 4 4-4\"/>",
  "chevron-right": "<path d=\"M6 4l4 4-4 4\"/>",
  "trash": "<path d=\"M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5\"/>",
  "image": "<rect x=\"2\" y=\"3\" width=\"12\" height=\"10\" rx=\"2\"/><circle cx=\"6\" cy=\"6.8\" r=\"1.2\"/><path d=\"M2.5 12l3.5-3.5 2.5 2.5 2-2 3 3\"/>",
  "folder": "<path d=\"M2 4.5a1 1 0 0 1 1-1h3l1.5 1.5H13a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z\"/>",
  "settings": "<path d=\"M2.5 5h6M11.5 5h2M2.5 11h2M7.5 11h6\"/><circle cx=\"10\" cy=\"5\" r=\"1.5\"/><circle cx=\"6\" cy=\"11\" r=\"1.5\"/>",
  "always-on-top": "<path d=\"M3 2.5h10M8 14V5.5M4.8 8.7 8 5.5l3.2 3.2\"/>",
  "opacity": "<path d=\"M8 2.5S3.5 7 3.5 9.5a4.5 4.5 0 0 0 9 0C12.5 7 8 2.5 8 2.5z\"/>",
  "fit": "<path d=\"M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10\"/>",
  "undo": "<path d=\"M4 6.5h5.5a3 3 0 0 1 0 6H6M4 6.5l2.5-2.5M4 6.5l2.5 2.5\"/>",
  "redo": "<path d=\"M12 6.5H6.5a3 3 0 0 0 0 6H10M12 6.5 9.5 4M12 6.5 9.5 9\"/>",
  "search": "<circle cx=\"7\" cy=\"7\" r=\"4.25\"/><path d=\"M10.2 10.2 13.5 13.5\"/>"
};
  function icon(name, size) {
    var s = size || 16;
    return '<svg class="sc-icon" width="' + s + '" height="' + s + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (icons[name] || '') + '</svg>';
  }
  function mount(root) {
    var list = (root || document).querySelectorAll('[data-icon]');
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      el.innerHTML = icon(el.getAttribute('data-icon'), parseInt(el.getAttribute('data-size'), 10) || 16);
    }
  }
  window.Softclub = { icons: icons, icon: icon, mount: mount };
})();
