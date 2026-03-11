(function () {
  const fillJsonButton = document.getElementById("fill-json-btn");
  const jsonTextArea = document.getElementById("application_json");
  const analyzeButton = document.getElementById("analyze-btn");
  const ocrStatusBanner = document.getElementById("ocr-status-banner");
  const ocrStatusMessage = document.getElementById("ocr-status-message");
  const ocrStatusError = document.getElementById("ocr-status-error");
  const compareInputs = document.getElementById("compare-inputs");
  const reviewModeInputs = document.querySelectorAll('input[name="review_mode"]');
  const modeOptionElements = document.querySelectorAll("#review-mode-selector .mode-option");

  if (fillJsonButton && jsonTextArea) {
    fillJsonButton.addEventListener("click", function () {
      const payload = {
        brand_name: getValue("brand_name"),
        class_type: getValue("class_type"),
        alcohol_content: getValue("alcohol_content"),
        net_contents: getValue("net_contents"),
        bottler_producer: getValue("bottler_producer"),
        country_of_origin: getValue("country_of_origin"),
        government_warning: getValue("government_warning"),
      };
      jsonTextArea.value = JSON.stringify(payload, null, 2);
    });
  }

  if (compareInputs && reviewModeInputs.length > 0) {
    reviewModeInputs.forEach(function (input) {
      input.addEventListener("change", function () {
        applyReviewMode(input.value);
      });
    });

    const selectedMode = Array.from(reviewModeInputs).find(function (input) {
      return input.checked;
    });
    applyReviewMode(selectedMode ? selectedMode.value : "label_only");
  }

  if (analyzeButton && ocrStatusBanner && ocrStatusMessage && ocrStatusError) {
    applyStatus({
      state: ocrStatusBanner.dataset.ocrState || "cold",
      ready: ocrStatusBanner.dataset.ocrReady === "true",
      message: ocrStatusMessage.textContent || "OCR status unavailable.",
      error: ocrStatusError.hidden ? null : ocrStatusError.textContent,
    });
    startOcrStatusPolling();
  }

  function getValue(id) {
    const element = document.getElementById(id);
    return element ? element.value : "";
  }

  function startOcrStatusPolling() {
    fetchStatus();
    window.setInterval(fetchStatus, 3000);
  }

  async function fetchStatus() {
    try {
      const response = await fetch("/api/v1/ocr/status", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      applyStatus(payload);
    } catch (_) {
      // Keep current UI state on transient fetch errors.
    }
  }

  function applyStatus(payload) {
    const state = typeof payload.state === "string" ? payload.state : "cold";
    const ready = payload.ready === true;
    const message = typeof payload.message === "string" ? payload.message : "OCR status unavailable.";
    const error = typeof payload.error === "string" && payload.error.length > 0 ? payload.error : null;

    ocrStatusBanner.classList.remove("alert-ocr-cold", "alert-ocr-warming", "alert-ocr-ready", "alert-ocr-failed");
    ocrStatusBanner.classList.add(`alert-ocr-${state}`);
    ocrStatusBanner.dataset.ocrState = state;
    ocrStatusBanner.dataset.ocrReady = ready ? "true" : "false";

    ocrStatusMessage.textContent = message;
    analyzeButton.disabled = !ready;

    if (error) {
      ocrStatusError.hidden = false;
      ocrStatusError.textContent = error;
    } else {
      ocrStatusError.hidden = true;
      ocrStatusError.textContent = "";
    }
  }

  function applyReviewMode(mode) {
    const compareMode = mode === "compare_application";
    compareInputs.classList.toggle("compare-inputs-hidden", !compareMode);

    modeOptionElements.forEach(function (option) {
      const input = option.querySelector('input[name="review_mode"]');
      if (!input) {
        return;
      }
      option.classList.toggle("mode-option-active", input.value === mode);
    });

    if (!compareMode) {
      clearCompareFields();
    }
  }

  function clearCompareFields() {
    [
      "brand_name",
      "class_type",
      "alcohol_content",
      "net_contents",
      "bottler_producer",
      "country_of_origin",
      "government_warning",
      "application_json",
    ].forEach(function (id) {
      const field = document.getElementById(id);
      if (field) {
        field.value = "";
      }
    });
  }
})();
