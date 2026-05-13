// Auto-calculate efficiency when hours are entered
document.addEventListener("DOMContentLoaded", function () {
    var inputs = document.querySelectorAll(".hours-input");
    function recalc() {
        var row = this.dataset.row;
        var hours = parseFloat(this.value) || 0;
        var workDone = parseInt(document.querySelector("input[name='work_done_" + row + "']").value) || 0;
        var cell = document.getElementById("eff_" + row);
        if (hours > 0 && workDone > 0) {
            cell.textContent = (workDone / hours).toFixed(2);
        } else {
            cell.textContent = "-";
        }
    }
    for (var i = 0; i < inputs.length; i++) {
        inputs[i].addEventListener("input", recalc);
        // trigger initial calculation if value exists
        recalc.call(inputs[i]);
    }
});
