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
  const batchModeInputs = document.querySelectorAll('input[name="batch_review_mode"]');
  const batchModeOptionElements = document.querySelectorAll("#batch-mode-selector .mode-option");
  const batchCompareInputs = document.getElementById("batch-compare-inputs");
  const batchHelpLabelOnly = document.getElementById("batch-help-label-only");
  const batchHelpCompare = document.getElementById("batch-help-compare");
  const batchFileInput = document.getElementById("batch_file");
  const imagesArchiveInput = document.getElementById("images_archive");
  const coverageCard = document.getElementById("coverage-card");
  const coverageRunState = document.getElementById("coverage-run-state");
  const coverageRunMessage = document.getElementById("coverage-run-message");
  const coverageRunExitCode = document.getElementById("coverage-run-exit-code");
  const coverageSummaryTable = document.getElementById("coverage-summary-table");
  const coverageEmptyMessage = document.getElementById("coverage-empty-message");
  const coverageGenerateBtn = document.getElementById("coverage-generate-btn");
  const coverageGenerateLabel = document.getElementById("coverage-generate-label");
  const coverageTotal = document.getElementById("coverage-total");
  const coverageCoveredLines = document.getElementById("coverage-covered-lines");
  const coverageNumStatements = document.getElementById("coverage-num-statements");
  const coverageHtmlLink = document.getElementById("coverage-html-link");
  const coverageHtmlMissing = document.getElementById("coverage-html-missing");
  const imageInput = document.getElementById("image");
  const imagePreviewWrap = document.getElementById("image-preview-wrap");
  const imagePreview = document.getElementById("image-preview");
  const lightbox = document.getElementById("image-lightbox");
  const lightboxImage = document.getElementById("image-lightbox-image");
  const lightboxTitle = document.getElementById("image-lightbox-title");
  let imagePreviewUrl = null;

  initializeModeSelectors();
  initializeImageLightbox();

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

  if (batchModeInputs.length > 0 && batchCompareInputs && batchHelpLabelOnly && batchHelpCompare) {
    batchModeInputs.forEach(function (input) {
      input.addEventListener("change", function () {
        applyBatchReviewMode(input.value);
      });
    });
    const selectedBatchMode = Array.from(batchModeInputs).find(function (input) {
      return input.checked;
    });
    applyBatchReviewMode(selectedBatchMode ? selectedBatchMode.value : "batch_label_only");
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

  if (coverageCard && coverageRunState && coverageRunMessage && coverageRunExitCode) {
    startCoverageStatusPolling();
  }

  if (imageInput && imagePreviewWrap && imagePreview) {
    imageInput.addEventListener("change", function () {
      const file = imageInput.files && imageInput.files[0] ? imageInput.files[0] : null;
      renderImagePreview(file);
    });

    const initialFile = imageInput.files && imageInput.files[0] ? imageInput.files[0] : null;
    renderImagePreview(initialFile);
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

  function initializeModeSelectors() {
    document.querySelectorAll(".mode-selector").forEach(function (group) {
      const options = group.querySelectorAll(".mode-option");
      const radios = group.querySelectorAll('input[type=\"radio\"]');
      if (options.length === 0 || radios.length === 0) {
        return;
      }
      const sync = function () {
        options.forEach(function (option) {
          const input = option.querySelector('input[type=\"radio\"]');
          option.classList.toggle("mode-option-active", Boolean(input && input.checked));
        });
      };
      radios.forEach(function (radio) {
        radio.addEventListener("change", sync);
      });
      options.forEach(function (option) {
        option.addEventListener("click", function () {
          const input = option.querySelector('input[type=\"radio\"]');
          if (!input || input.disabled) {
            return;
          }
          if (!input.checked) {
            input.checked = true;
            input.dispatchEvent(new Event("change", { bubbles: true }));
          } else {
            sync();
          }
        });
      });
      sync();
    });
  }

  function renderImagePreview(file) {
    if (!imagePreviewWrap || !imagePreview) {
      return;
    }
    if (!file || (file.type && !file.type.startsWith("image/"))) {
      if (imagePreviewUrl) {
        URL.revokeObjectURL(imagePreviewUrl);
        imagePreviewUrl = null;
      }
      imagePreview.removeAttribute("src");
      imagePreviewWrap.hidden = true;
      return;
    }
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
    }
    imagePreviewUrl = URL.createObjectURL(file);
    imagePreview.src = imagePreviewUrl;
    imagePreviewWrap.hidden = false;
  }

  function initializeImageLightbox() {
    if (!lightbox || !lightboxImage) {
      return;
    }
    const zoomableImages = document.querySelectorAll(".js-lightbox-image");
    if (zoomableImages.length === 0) {
      return;
    }
    zoomableImages.forEach(function (img) {
      img.addEventListener("click", function () {
        const source = img.getAttribute("src");
        if (!source) {
          return;
        }
        lightboxImage.setAttribute("src", source);
        if (lightboxTitle) {
          lightboxTitle.textContent = img.dataset.lightboxTitle || "Image";
        }
        lightbox.hidden = false;
        lightbox.setAttribute("aria-hidden", "false");
      });
    });
    lightbox.querySelectorAll("[data-lightbox-close]").forEach(function (target) {
      target.addEventListener("click", closeLightbox);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !lightbox.hidden) {
        closeLightbox();
      }
    });
  }

  function closeLightbox() {
    if (!lightbox || !lightboxImage) {
      return;
    }
    lightbox.hidden = true;
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImage.removeAttribute("src");
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

  function applyBatchReviewMode(mode) {
    const compareMode = mode === "batch_compare_application";
    batchCompareInputs.classList.toggle("compare-inputs-hidden", !compareMode);
    batchHelpLabelOnly.classList.toggle("compare-inputs-hidden", compareMode);
    batchHelpCompare.classList.toggle("compare-inputs-hidden", !compareMode);

    batchModeOptionElements.forEach(function (option) {
      const input = option.querySelector('input[name="batch_review_mode"]');
      if (!input) {
        return;
      }
      option.classList.toggle("mode-option-active", input.value === mode);
    });

    if (batchFileInput) {
      batchFileInput.required = compareMode;
    }
    if (imagesArchiveInput) {
      imagesArchiveInput.required = true;
    }
  }

  function startCoverageStatusPolling() {
    const initialState = coverageCard.dataset.coverageState || "idle";
    if (initialState === "running") {
      fetchCoverageStatus();
      window.setInterval(fetchCoverageStatus, 2000);
    }
  }

  async function fetchCoverageStatus() {
    try {
      const response = await fetch("/ui/diagnostics/coverage/status", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      applyCoverageStatus(payload);
    } catch (_) {
      // Keep rendered state on transient fetch errors.
    }
  }

  function applyCoverageStatus(payload) {
    if (!payload || !payload.coverage_run) {
      return;
    }

    const run = payload.coverage_run;
    const coverage = payload.coverage || {};
    const runState = typeof run.state === "string" ? run.state : "idle";
    const runMessage = typeof run.message === "string" ? run.message : "Coverage status unavailable.";
    const runExitCode = run.last_exit_code === null || run.last_exit_code === undefined ? "N/A" : String(run.last_exit_code);

    coverageRunState.textContent = runState;
    coverageRunMessage.textContent = runMessage;
    coverageRunExitCode.textContent = runExitCode;
    coverageCard.dataset.coverageState = runState;

    if (coverageGenerateBtn && coverageGenerateLabel) {
      const isRunning = runState === "running";
      coverageGenerateBtn.disabled = isRunning;
      coverageGenerateLabel.textContent = isRunning ? "Coverage Running..." : "Generate Coverage";
    }

    const hasCoverage = coverage.available === true;
    if (coverageSummaryTable) {
      coverageSummaryTable.hidden = !hasCoverage;
    }
    if (coverageEmptyMessage) {
      coverageEmptyMessage.hidden = hasCoverage;
    }

    if (hasCoverage) {
      if (coverageTotal) {
        coverageTotal.textContent =
          coverage.total_percent === null || coverage.total_percent === undefined
            ? "N/A"
            : String(coverage.total_percent);
      }
      if (coverageCoveredLines) {
        coverageCoveredLines.textContent =
          coverage.covered_lines === null || coverage.covered_lines === undefined ? "N/A" : String(coverage.covered_lines);
      }
      if (coverageNumStatements) {
        coverageNumStatements.textContent =
          coverage.num_statements === null || coverage.num_statements === undefined
            ? "N/A"
            : String(coverage.num_statements);
      }
      if (coverageHtmlLink && coverageHtmlMissing) {
        const htmlUrl = typeof coverage.html_url === "string" ? coverage.html_url : "";
        if (htmlUrl.length > 0) {
          coverageHtmlLink.hidden = false;
          coverageHtmlLink.href = htmlUrl;
          coverageHtmlMissing.hidden = true;
        } else {
          coverageHtmlLink.hidden = true;
          coverageHtmlLink.href = "#";
          coverageHtmlMissing.hidden = false;
        }
      }
    }
  }
})();
