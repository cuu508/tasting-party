window.addEventListener("load", (event) => {
    function applyFilters() {
        var v = 0;
        // Table
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

        // Events
        document.querySelectorAll(".changes li").forEach(function (li) {
            if (category.value && !li.classList.contains(category.value)) {
                li.style.display = "none";
            } else {
                li.style.display = "";
            }
        });
    }

    showRedOnly.addEventListener("change", applyFilters);
    category.addEventListener("change", applyFilters);
});
