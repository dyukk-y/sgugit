(() => {
  const tg = window.Telegram?.WebApp;
  try { tg?.ready(); tg?.expand(); } catch (_) {}
  const screens = [...document.querySelectorAll(".screen")];
  const navItems = [...document.querySelectorAll(".nav-item")];
  const toast = document.getElementById("toast");
  let role = "student";
  let toastTimer;

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1900);
    try { tg?.HapticFeedback?.impactOccurred("light"); } catch (_) {}
  }

  function openScreen(id) {
    screens.forEach(screen => screen.classList.toggle("active", screen.id === id));
    navItems.forEach(item => item.classList.toggle("active", item.dataset.screen === id));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.addEventListener("click", event => {
    const nav = event.target.closest("[data-screen]");
    if (nav) {
      openScreen(nav.dataset.screen);
      return;
    }
    const toggle = event.target.closest(".toggle");
    if (toggle) {
      toggle.classList.toggle("on");
      showToast(toggle.classList.contains("on") ? "Настройка включена" : "Настройка выключена");
      return;
    }
    const segmented = event.target.closest(".segmented button");
    if (segmented) {
      segmented.parentElement.querySelectorAll("button").forEach(btn => btn.classList.toggle("selected", btn === segmented));
      showToast("Демо: переключение периода");
      return;
    }
    const roleButton = event.target.closest(".role-choice");
    if (roleButton) {
      role = roleButton.dataset.role;
      document.querySelectorAll(".role-choice").forEach(btn => {
        const selected = btn === roleButton;
        btn.classList.toggle("selected", selected);
        btn.querySelector("i").textContent = selected ? "✓" : "○";
      });
      if (role === "teacher") {
        openScreen("teacherScreen");
        showToast("Демонстрация кабинета преподавателя");
      } else {
        openScreen("homeScreen");
        showToast("Демонстрация режима студента");
      }
    }
  });

  document.getElementById("profileShortcut")?.addEventListener("click", () => openScreen("profileScreen"));
  document.querySelectorAll(".date-strip b").forEach((day, index) => {
    day.addEventListener("click", () => {
      document.querySelectorAll(".date-strip b").forEach(item => item.style.color = item === day ? "#c6e67d" : "#e8e1ed");
      showToast(index === 0 ? "Выбран текущий день" : "Демо: выбран другой день");
    });
  });
})();