// ==========================================================================
// 1. CSRF HELPER FOR DJANGO POST REQUESTS
// ==========================================================================
function getCsrfToken() {
  const name = "csrftoken=";
  const decodedCookie = decodeURIComponent(document.cookie);
  const parts = decodedCookie.split(";");
  for (let i = 0; i < parts.length; i++) {
    let c = parts[i].trim();
    if (c.indexOf(name) === 0) {
      return c.substring(name.length, c.length);
    }
  }
  return "";
}

// ==========================================================================
// 2. 3D MDF STREET SIGN INTERACTIVE BUILDER
// ==========================================================================
function updatePreviewText(text) {
  const textDisplay = document.getElementById("preview-text-display");
  const charCount = document.getElementById("char-count");
  const uppercaseText = (text || "").toUpperCase();

  if (textDisplay) {
    textDisplay.textContent =
      uppercaseText.trim() === "" ? "YOUR TEXT HERE" : uppercaseText;

    if (uppercaseText.length > 18) {
      textDisplay.style.fontSize = "1.05rem";
    } else if (uppercaseText.length > 12) {
      textDisplay.style.fontSize = "1.25rem";
    } else {
      textDisplay.style.fontSize = "1.45rem";
    }
  }

  if (charCount) {
    charCount.textContent = `${(text || "").length} / 24 characters`;
    charCount.style.color = (text || "").length >= 24 ? "#e11d48" : "#6c757d";
  }
}

function setFinish(finishClass, activeBtn = null) {
  const mockup = document.getElementById("mdf-sign-mockup");
  if (mockup) {
    mockup.className = "mdf-mockup " + finishClass;
  }

  const finishButtons = document.querySelectorAll(".finish-btn");
  finishButtons.forEach((btn) => btn.classList.remove("active"));

  const targetBtn =
    activeBtn ||
    document.querySelector(`.finish-btn[data-finish="${finishClass}"]`);
  if (targetBtn) {
    targetBtn.classList.add("active");
    const finishInput = document.getElementById("sign-finish-input");
    if (finishInput && targetBtn.dataset.finishLabel) {
      finishInput.value = targetBtn.dataset.finishLabel;
    }
  }
}

// ==========================================================================
// 3. PHOTO LASER VECTORIZER & MOCKUP STUDIO
// ==========================================================================
const vectorizerState = {
  jobId: null,
  activeMaterial: "slate",
  previews: {
    slate: null,
    mdf: null,
    acrylic: null,
  },
};

function updateVectorizerMaterialUI(materialKey) {
  vectorizerState.activeMaterial = materialKey;

  document.querySelectorAll(".material-switch-btn").forEach((btn) => {
    const isMatch = btn.dataset.material === materialKey;
    btn.classList.toggle("active", isMatch);
    if (isMatch) {
      const caption = document.getElementById("active-material-caption");
      if (caption) {
        caption.textContent = `Material: ${btn.dataset.materialLabel} • Watermarked Proof`;
      }
      const modalSelect = document.getElementById("order-material-select");
      if (modalSelect && btn.dataset.materialLabel) {
        modalSelect.value = btn.dataset.materialLabel;
      }
    }
  });

  const proofImg = document.getElementById("proof-raster-img");
  if (proofImg && vectorizerState.previews[materialKey]) {
    proofImg.src = vectorizerState.previews[materialKey];
  }

  const textOverlay = document.getElementById("proof-live-text-overlay");
  if (textOverlay) {
    textOverlay.className = `proof-live-text-overlay material-${materialKey}`;
  }
}

function updateVectorizerLiveText(rawText) {
  const textSpan = document.getElementById("proof-live-text-span");
  const charCounter = document.getElementById("vector-char-count");
  const modalTextInput = document.getElementById("order-custom-text-modal");
  const clean = (rawText || "").toUpperCase();

  if (textSpan) {
    textSpan.textContent = clean;
    if (clean.length > 22) {
      textSpan.style.fontSize = "0.95rem";
    } else if (clean.length > 14) {
      textSpan.style.fontSize = "1.1rem";
    } else {
      textSpan.style.fontSize = "1.3rem";
    }
  }
  if (charCounter) {
    charCounter.textContent = `${clean.length} / 32`;
  }
  if (modalTextInput && modalTextInput !== document.activeElement) {
    modalTextInput.value = clean;
  }
}

async function processPhotoPreview({ file = null, useSample = false } = {}) {
  const loadingOverlay = document.getElementById("proof-loading-overlay");
  const statusText = document.getElementById("upload-status-text");
  const jobBadge = document.getElementById("job-ref-badge");
  const lockBadge = document.getElementById("svg-lock-badge");
  const customTextInput = document.getElementById("vector-custom-text");

  if (loadingOverlay) loadingOverlay.classList.remove("d-none");
  if (statusText) {
    statusText.textContent = "Vectorizing image & generating LightBurn layers...";
  }

  const formData = new FormData();
  if (file) {
    formData.append("image", file);
  }
  if (useSample) {
    formData.append("use_sample", "1");
  }
  formData.append("material", vectorizerState.activeMaterial);
  if (customTextInput && customTextInput.value) {
    formData.append("custom_text", customTextInput.value);
  }

  try {
    const response = await fetch("/api/process-preview/", {
      method: "POST",
      headers: {
        "X-CSRFToken": getCsrfToken(),
      },
      body: formData,
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Failed to generate preview.");
    }

    vectorizerState.jobId = data.job_id;
    vectorizerState.previews = data.previews;

    updateVectorizerMaterialUI(vectorizerState.activeMaterial);

    if (jobBadge) {
      jobBadge.textContent = `LightBurn Job #${data.job_id.slice(0, 8).toUpperCase()}`;
      jobBadge.className = "badge bg-dark text-white";
    }
    if (lockBadge) {
      lockBadge.textContent = "🔒 SVG Saved Server-Side";
      lockBadge.className = "badge bg-success";
    }
    if (statusText) {
      statusText.textContent =
        "✓ 3-Layer LightBurn SVG generated & stored privately on server.";
    }
  } catch (err) {
    if (statusText) {
      statusText.textContent = `Error: ${err.message}`;
    }
  } finally {
    if (loadingOverlay) loadingOverlay.classList.add("d-none");
  }
}

function updateModalEstimatedPrice() {
  const sizeSelect = document.getElementById("order-size-select");
  const qtyInput = document.getElementById("order-quantity");
  const fulfillSelect = document.getElementById("order-fulfillment");
  const priceDisplay = document.getElementById("modal-price-display");

  if (!sizeSelect || !priceDisplay) return;
  const selectedOpt = sizeSelect.options[sizeSelect.selectedIndex];
  const basePrice = parseFloat(selectedOpt?.dataset.price || "12.00");
  const qty = Math.max(1, parseInt(qtyInput?.value || "1", 10));
  const shippingOpt = fulfillSelect?.options[fulfillSelect.selectedIndex];
  const shipping = parseFloat(shippingOpt?.dataset.shipping || "3.50");

  const total = basePrice * qty + shipping;
  priceDisplay.textContent = `£${total.toFixed(2)}`;
  priceDisplay.dataset.numericTotal = total.toFixed(2);
}

// ==========================================================================
// 4. INITIALIZE EVENT LISTENERS
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  // A. Street Sign Builder
  const textInput = document.getElementById("custom-text-input");
  if (textInput) {
    textInput.addEventListener("input", (e) => {
      updatePreviewText(e.target.value);
    });
  }

  document.querySelectorAll(".finish-btn[data-finish]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setFinish(btn.dataset.finish, btn);
    });
  });

  // B. Photo Vectorizer Dropzone & Controls
  const dropzone = document.getElementById("vector-dropzone");
  const fileInput = document.getElementById("vector-file-input");

  if (dropzone && fileInput) {
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });

    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => {
      dropzone.classList.remove("dragover");
    });
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        processPhotoPreview({ file: e.dataTransfer.files[0] });
      }
    });

    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        processPhotoPreview({ file: e.target.files[0] });
      }
    });

    // Automatically generate a live sample preview on first load so the studio is immediately interactive
    processPhotoPreview({ useSample: true });
  }

  const sampleBtn = document.getElementById("try-sample-btn");
  const sampleInlineBtn = document.getElementById("try-sample-inline-btn");
  [sampleBtn, sampleInlineBtn].forEach((btn) => {
    if (btn) {
      btn.addEventListener("click", () => processPhotoPreview({ useSample: true }));
    }
  });

  // Material switcher buttons
  document.querySelectorAll(".material-switch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      updateVectorizerMaterialUI(btn.dataset.material);
    });
  });

  // Live Custom Text input on Vectorizer
  const vectorTextInput = document.getElementById("vector-custom-text");
  if (vectorTextInput) {
    vectorTextInput.addEventListener("input", (e) => {
      updateVectorizerLiveText(e.target.value);
    });
  }

  // Block right-click & drag on proof stage
  const proofStage = document.getElementById("proof-stage");
  if (proofStage) {
    proofStage.addEventListener("contextmenu", (e) => e.preventDefault());
    proofStage.addEventListener("dragstart", (e) => e.preventDefault());
  }

  // Modal price calculator
  ["order-size-select", "order-quantity", "order-fulfillment"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", updateModalEstimatedPrice);
      el.addEventListener("input", updateModalEstimatedPrice);
    }
  });
  updateModalEstimatedPrice();

  // C. Submit Physical Order Modal Form
  const physicalOrderForm = document.getElementById("physical-order-form");
  if (physicalOrderForm) {
    physicalOrderForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const alertBox = document.getElementById("vectorizer-alert-box");
      const priceDisplay = document.getElementById("modal-price-display");
      const formData = new FormData(physicalOrderForm);
      if (vectorizerState.jobId) {
        formData.append("job_id", vectorizerState.jobId);
      }
      formData.append("product_category", "photo_engraving");
      formData.append(
        "estimated_price",
        priceDisplay?.dataset.numericTotal || "15.50"
      );

      const res = await fetch("/api/submit-order/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: formData,
      });
      const result = await res.json();

      if (alertBox) {
        alertBox.className = `alert ${result.ok ? "alert-success" : "alert-danger"} mb-3`;
        alertBox.textContent = result.message || result.error;
        alertBox.classList.remove("d-none");
      }

      if (result.ok) {
        const modalEl = document.getElementById("physicalOrderModal");
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();
        physicalOrderForm.reset();
        updateModalEstimatedPrice();
      }
    });
  }

  // D. Submit Digital LightBurn SVG License Form (£4.99)
  const digitalSvgForm = document.getElementById("digital-svg-form");
  if (digitalSvgForm) {
    digitalSvgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const resultBox = document.getElementById("digital-download-result");
      const payload = {
        job_id: vectorizerState.jobId,
        customer_name: document.getElementById("digital-customer-name")?.value || "",
        customer_email: document.getElementById("digital-customer-email")?.value || "",
        custom_text: document.getElementById("vector-custom-text")?.value || "",
      };

      const res = await fetch("/api/unlock-digital-svg/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (resultBox) {
        resultBox.classList.remove("d-none");
        if (data.ok) {
          resultBox.className = "alert alert-success mb-0";
          resultBox.innerHTML = `
            <strong>✓ License Unlocked (${data.order_reference})!</strong>
            <p class="small mb-2">Your expiring one-time LightBurn SVG link is ready below (valid for 1 download):</p>
            <a href="${data.download_url}" class="btn btn-sm btn-dark fw-bold w-100">
              ⬇ Download Clean LightBurn .SVG File Now
            </a>
          `;
        } else {
          resultBox.className = "alert alert-danger mb-0";
          resultBox.textContent = data.error || "Could not unlock SVG.";
        }
      }
    });
  }

  // E. Street Sign Page Order Form
  const streetSignForm = document.getElementById("street-sign-order-form");
  if (streetSignForm) {
    streetSignForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const alertEl = document.getElementById("sign-order-alert");
      const pkgSelect = document.getElementById("sign-package-select");
      const fulfillSelect = document.getElementById("sign-fulfillment");
      const basePrice = parseFloat(
        pkgSelect?.options[pkgSelect.selectedIndex]?.dataset.price || "25.00"
      );
      const shipping =
        fulfillSelect?.value === "birmingham_collection" ? 0.0 : 3.5;

      const formData = new FormData(streetSignForm);
      formData.append("estimated_price", (basePrice + shipping).toFixed(2));

      const res = await fetch("/api/submit-order/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: formData,
      });
      const data = await res.json();
      if (alertEl) {
        alertEl.className = `alert ${data.ok ? "alert-success" : "alert-danger"} mb-3`;
        alertEl.textContent = data.message || data.error;
        alertEl.classList.remove("d-none");
      }
    });
  }

  // F. Homepage Direct Order Form & Quick Prefill Buttons
  document.querySelectorAll(".quick-prefill-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const catSelect = document.getElementById("home-product-category");
      const priceInput = document.getElementById("home-estimated-price");
      if (catSelect && btn.dataset.prefillCategory) {
        catSelect.value = btn.dataset.prefillCategory;
      }
      if (priceInput && btn.dataset.prefillPrice) {
        priceInput.value = btn.dataset.prefillPrice;
      }
    });
  });

  const homeOrderForm = document.getElementById("homepage-order-form");
  if (homeOrderForm) {
    homeOrderForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const alertEl = document.getElementById("home-order-alert");
      const catSelect = document.getElementById("home-product-category");
      const fulfillSelect = document.getElementById("home-fulfillment");
      const basePrice = parseFloat(
        catSelect?.options[catSelect.selectedIndex]?.dataset.price || "12.00"
      );
      const shipping =
        fulfillSelect?.value === "birmingham_collection" ? 0.0 : 3.5;

      const formData = new FormData(homeOrderForm);
      formData.set("estimated_price", (basePrice + shipping).toFixed(2));

      const res = await fetch("/api/submit-order/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: formData,
      });
      const data = await res.json();
      if (alertEl) {
        alertEl.className = `alert ${data.ok ? "alert-success" : "alert-danger"} mt-3 mb-0`;
        alertEl.textContent = data.message || data.error;
        alertEl.classList.remove("d-none");
      }
      if (data.ok) {
        homeOrderForm.reset();
      }
    });
  }
});