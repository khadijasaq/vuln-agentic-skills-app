/*
 * A very small amount of page behaviour.
 *
 * TaskBot deliberately uses almost no browser code. The pages are ordinary HTML
 * forms that work whether or not this file loads, which keeps the app simple to
 * read and impossible to break in interesting ways.
 *
 * There are exactly two jobs here:
 *   1. Let an activity row expand to show its detail.
 *   2. Put the cursor in the chat box when the page opens.
 *
 * Nothing here contacts the network.
 */

document.addEventListener('DOMContentLoaded', function () {
  // 1. Clicking an activity row shows or hides its detail.
  document.querySelectorAll('.activity-head').forEach(function (head) {
    head.addEventListener('click', function () {
      head.parentElement.classList.toggle('open');
    });
  });

  // 2. Put the cursor straight into the message box, so a person can start typing
  //    the moment the page appears.
  var box = document.querySelector('.composer input');
  if (box) {
    box.focus();
  }
});
