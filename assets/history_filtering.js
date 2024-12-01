window.addEventListener("load", (event) => {
    function applyFilters() {
        // Update URL
        if (window.history && window.history.replaceState) {
            var hashParts = [];
            if (category.value) {
                hashParts.push("category=" + category.value);
            }
            if (search.value) {
                hashParts.push("search=" + encodeURIComponent(search.value));
            }

            window.history.replaceState({}, "", "#" + hashParts.join("&"));
        }

        // Events
        var totalShown = 0;
        document.querySelectorAll(".changes").forEach(function (div) {
            var shown = 0;
            div.querySelectorAll("li").forEach(function (li) {
                if (category.value && !li.classList.contains(category.value)) {
                    li.style.display = "none";
                    return;
                }

                if (search.value && li.dataset.domain.indexOf(search.value) == -1) {
                    li.style.display = "none";
                    return;
                }

                li.style.display = "";
                shown += 1;
            });
            div.style.display = shown > 0 ? "" : "none";
            totalShown += shown;
        });
        changesEmpty.style.display = totalShown == 0 ? "" : "none";
    }

    category.addEventListener("change", applyFilters);
    // Wait 300ms after keyup events to let the user finish typing
    let applyFiltersTimer;
    search.addEventListener("keyup", function () {
        clearTimeout(applyFiltersTimer);
        applyFiltersTimer = setTimeout(applyFilters, 300);
    });

    // Apply filters from hash
    if (window.location.hash) {
        var params = {};
        var hashParts = window.location.hash.substring(1).split("&");
        for (pair of hashParts) {
            var nameValue = pair.split("=");
            params[nameValue[0]] = nameValue[1];
        }

        category.value = params.category || "";
        search.value = params.search || "";
        applyFilters();
    }
});
