// Toast notifications
function toast(msg, type = "success") {
  const c = document.getElementById("toast-container");
  if (!c) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${type === "success" ? "✓" : "✗"}</span> ${msg}`;
  c.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// Generic POST form helper
async function postForm(url, data) {
  const form = new FormData();
  Object.entries(data).forEach(([k, v]) => form.append(k, v));
  const r = await fetch(url, { method: "POST", body: form });
  return r.json();
}

// Scan button
function initScanButton() {
  const btn = document.getElementById("scan-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const accountId = btn.dataset.accountId;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Escaneando...';
    try {
      const res = await fetch(`/api/scan/${accountId}`, { method: "POST" });
      const data = await res.json();
      toast(`Scan completado: ${data.scanned} emails nuevos procesados`);
      setTimeout(() => location.reload(), 1500);
    } catch {
      toast("Error durante el scan", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = "Escanear ahora";
    }
  });
}

// Breach check button
function initBreachCheck() {
  const btn = document.getElementById("breach-check-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const accountId = btn.dataset.accountId;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Verificando...';
    try {
      const res = await postForm("/api/breaches/check", { account_id: accountId });
      toast(`${res.breaches} brechas encontradas`);
      setTimeout(() => location.reload(), 1500);
    } catch {
      toast("Error al verificar brechas", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = "Verificar brechas";
    }
  });
}

// Email actions: unsubscribe / block
function initEmailActions() {
  document.querySelectorAll(".action-unsubscribe").forEach(btn => {
    btn.addEventListener("click", async () => {
      const { accountId, sender } = btn.dataset;
      if (!confirm(`¿Desuscribir de ${sender}?`)) return;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      const res = await postForm("/api/emails/unsubscribe", { account_id: accountId, sender });
      if (res.ok) {
        toast(`Desuscripto de ${sender}`);
        btn.closest("tr")?.remove();
      } else {
        toast(res.reason || "Error", "error");
        btn.disabled = false;
        btn.innerHTML = "Desuscribir";
      }
    });
  });

  document.querySelectorAll(".action-block").forEach(btn => {
    btn.addEventListener("click", async () => {
      const { accountId, sender } = btn.dataset;
      const del = confirm(`¿Bloquear ${sender}?\n\n"Aceptar" también elimina emails existentes.\n"Cancelar" solo crea el filtro.`);
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      const res = await postForm("/api/emails/block", {
        account_id: accountId,
        sender,
        delete_existing: del,
      });
      if (res.ok) {
        toast(`${sender} bloqueado (${res.emails_trashed} emails eliminados)`);
        btn.closest("tr")?.remove();
      } else {
        toast(res.reason || "Error al bloquear", "error");
        btn.disabled = false;
        btn.innerHTML = "Bloquear";
      }
    });
  });
}

// Delete account
function initDeleteAccount() {
  document.querySelectorAll(".action-delete-account").forEach(btn => {
    btn.addEventListener("click", async () => {
      const { accountId, email } = btn.dataset;
      if (!confirm(`¿Eliminar cuenta ${email}? Se borrarán todos los datos asociados.`)) return;
      const res = await fetch(`/accounts/${accountId}`, { method: "DELETE" });
      if (res.ok) {
        toast("Cuenta eliminada");
        setTimeout(() => location.reload(), 1000);
      } else {
        toast("Error al eliminar", "error");
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initScanButton();
  initBreachCheck();
  initEmailActions();
  initDeleteAccount();
});
