window.addEventListener("load", (event) => {
    function applyFilters() {
        var v = 0;
        sites.querySelectorAll("tr.site").forEach(function (tr) {
            if (showRedOnly.checked && !tr.classList.contains("red")) {
                tr.style.display = "none";
                return;
            }
            if (category.value && !tr.classList.contains(category.value)) {
                tr.style.display = "none";
                return;
            }

            tr.style.display = "";
            v += 1;
        });
        numVisible.innerText = v;
    }

    showRedOnly.addEventListener("change", applyFilters);
    category.addEventListener("change", applyFilters);
});
