(function () {
  "use strict";

  const nativeAlert = window.alert ? window.alert.bind(window) : null;

  function byId(id) {
    return document.getElementById(id);
  }

  function normalizeType(type) {
    if (type === "error") return "danger";
    if (["success", "danger", "warning", "info", "primary", "secondary"].includes(type)) return type;
    return "info";
  }

  function toast(message, type = "info", options = {}) {
    const container = byId("appToastContainer");
    if (!container || !window.bootstrap) {
      if (nativeAlert) nativeAlert(String(message || ""));
      return;
    }

    const safeType = normalizeType(type);
    const toastEl = document.createElement("div");
    toastEl.className = `toast align-items-center text-bg-${safeType} border-0`;
    toastEl.setAttribute("role", safeType === "danger" ? "alert" : "status");
    toastEl.setAttribute("aria-live", safeType === "danger" ? "assertive" : "polite");
    toastEl.setAttribute("aria-atomic", "true");

    const row = document.createElement("div");
    row.className = "d-flex";

    const body = document.createElement("div");
    body.className = "toast-body";
    body.textContent = String(message || "");

    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close btn-close-white me-2 m-auto";
    close.setAttribute("data-bs-dismiss", "toast");
    close.setAttribute("aria-label", "Close");

    row.append(body, close);
    toastEl.append(row);
    container.appendChild(toastEl);

    toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
    const delay = Number.isFinite(options.delay) ? options.delay : (safeType === "danger" ? 7000 : 4200);
    new bootstrap.Toast(toastEl, { delay }).show();
  }

  function confirmDialog(options = {}) {
    const message = String(options.message || options.confirm || "");
    const modalEl = byId("appConfirmModal");
    if (!modalEl || !window.bootstrap) {
      return Promise.resolve(window.confirm(message));
    }

    const titleEl = byId("appConfirmTitle");
    const messageEl = byId("appConfirmMessage");
    const okBtn = byId("appConfirmOk");
    if (!titleEl || !messageEl || !okBtn) {
      return Promise.resolve(window.confirm(message));
    }

    titleEl.textContent = options.title || "確認";
    messageEl.textContent = message;
    okBtn.textContent = options.okLabel || "実行";
    okBtn.className = `btn ${options.okClass || "btn-danger"}`;

    return new Promise((resolve) => {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

      function cleanup(result) {
        okBtn.removeEventListener("click", onOk);
        modalEl.removeEventListener("hidden.bs.modal", onHidden);
        resolve(result);
      }

      function onOk() {
        cleanup(true);
        modal.hide();
      }

      function onHidden() {
        cleanup(false);
      }

      okBtn.addEventListener("click", onOk);
      modalEl.addEventListener("hidden.bs.modal", onHidden, { once: true });
      modal.show();
    });
  }

  function setButtonBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      if (!button.dataset.appOriginalHtml) {
        button.dataset.appOriginalHtml = button.innerHTML;
      }
      button.disabled = true;
      button.innerHTML = `<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>${label || "処理中..."}`;
      return;
    }

    if (button.dataset.appOriginalHtml) {
      button.innerHTML = button.dataset.appOriginalHtml;
      delete button.dataset.appOriginalHtml;
    }
    button.disabled = false;
  }

  function applyBusyState(form, submitter) {
    if (!form) return;
    if (!form.matches("[data-busy-form]") && !(submitter && submitter.dataset.busyLabel)) return;

    const targets = submitter
      ? [submitter]
      : Array.from(form.querySelectorAll("button[type='submit'], input[type='submit']"));

    targets.forEach((button) => {
      if (button.tagName === "BUTTON") {
        setButtonBusy(button, true, button.dataset.busyLabel);
      } else {
        button.disabled = true;
      }
    });
  }

  function submitFormAfterConfirm(form, submitter) {
    form.dataset.appConfirmed = "1";
    if (submitter && typeof form.requestSubmit === "function") {
      form.requestSubmit(submitter);
      return;
    }
    form.submit();
  }

  async function handleConfirmClick(event) {
    const trigger = event.target.closest("[data-confirm]");
    if (!trigger) return;

    const form = trigger.closest("form");
    const isSubmitter = form && (trigger.matches("button[type='submit']") || trigger.matches("input[type='submit']"));
    const isLink = trigger.tagName === "A" && trigger.href;

    if (!isSubmitter && !isLink) return;

    event.preventDefault();
    const ok = await confirmDialog({
      title: trigger.dataset.confirmTitle,
      message: trigger.dataset.confirm,
      okLabel: trigger.dataset.confirmOkLabel,
      okClass: trigger.dataset.confirmOkClass
    });
    if (!ok) return;

    if (isSubmitter) {
      submitFormAfterConfirm(form, trigger);
    } else if (isLink) {
      window.location.href = trigger.href;
    }
  }

  async function handleConfirmSubmit(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.dataset.appConfirmed === "1") {
      delete form.dataset.appConfirmed;
      applyBusyState(form, event.submitter);
      return;
    }

    if (!form.matches("[data-confirm]")) {
      applyBusyState(form, event.submitter);
      return;
    }

    event.preventDefault();
    const ok = await confirmDialog({
      title: form.dataset.confirmTitle,
      message: form.dataset.confirm,
      okLabel: form.dataset.confirmOkLabel,
      okClass: form.dataset.confirmOkClass
    });
    if (ok) submitFormAfterConfirm(form, event.submitter);
  }

  function initSidebar() {
    document.querySelectorAll("[data-app-sidebar-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        document.body.classList.toggle("app-sidebar-open");
      });
    });

    document.querySelectorAll(".app-nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (window.matchMedia("(max-width: 991.98px)").matches) {
          document.body.classList.remove("app-sidebar-open");
        }
      });
    });
  }

  function initValidationState() {
    document.addEventListener("invalid", (event) => {
      if (event.target instanceof HTMLElement) {
        event.target.classList.add("is-invalid");
      }
    }, true);

    document.addEventListener("input", (event) => {
      if (event.target instanceof HTMLElement) {
        event.target.classList.remove("is-invalid");
      }
    });

    document.addEventListener("change", (event) => {
      if (event.target instanceof HTMLElement) {
        event.target.classList.remove("is-invalid");
      }
    });
  }

  window.AppUI = {
    toast,
    confirm: confirmDialog,
    setButtonBusy,
    nativeAlert
  };

  window.showAppError = function (message) {
    toast(message, "danger");
  };

  window.appAlert = toast;

  window.alert = function (message) {
    toast(message, "warning");
  };

  document.addEventListener("click", handleConfirmClick);
  document.addEventListener("submit", handleConfirmSubmit);
  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initValidationState();
  });
}());
