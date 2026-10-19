/* Patinho • Rádio Habbler | interações do fan-site */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const audio = byId("radio-audio");
  const playButton = byId("btn-play");
  const playIcon = byId("icon-play");
  const pauseIcon = byId("icon-pause");
  const radioStatus = byId("radio-status");
  const radioPanel = document.querySelector(".radio-panel");
  const volume = byId("volume");

  function setPlayerState(playing, message) {
    if (!playButton) return;
    playIcon.hidden = playing;
    pauseIcon.hidden = !playing;
    playButton.setAttribute("aria-label", playing ? "Pausar rádio" : "Tocar rádio");
    radioPanel.classList.toggle("playing", playing);
    if (message) radioStatus.textContent = message;
  }

  if (audio && playButton) {
    audio.volume = Number(volume.value) / 100;
    playButton.addEventListener("click", async () => {
      if (!audio.paused) {
        audio.pause();
        setPlayerState(false, "Rádio pausada");
        return;
      }
      radioStatus.textContent = "Conectando à rádio…";
      try {
        await audio.play();
        setPlayerState(true, "Ao vivo agora");
      } catch (error) {
        setPlayerState(false, "Não foi possível iniciar");
        console.warn("Falha no player de rádio:", error);
      }
    });
    audio.addEventListener("ended", () => setPlayerState(false, "Rádio encerrada"));
    audio.addEventListener("error", () => setPlayerState(false, "Erro ao conectar"));
    volume.addEventListener("input", () => { audio.volume = Number(volume.value) / 100; });
  }

  const mainNav = byId("main-nav");
  const menuButton = byId("menu-button");
  if (menuButton && mainNav) {
    menuButton.addEventListener("click", () => {
      const open = mainNav.classList.toggle("open");
      menuButton.setAttribute("aria-expanded", String(open));
    });
    mainNav.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => {
      mainNav.classList.remove("open");
      menuButton.setAttribute("aria-expanded", "false");
    }));
  }

  async function atualizarStatus() {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error("status indisponível");
      const data = await response.json();
      const online = Boolean(data.online);
      byId("stat-online").textContent = online ? "ao vivo" : "pausado";
      byId("stat-servidores").textContent = (data.servidores || 0).toLocaleString("pt-BR");
      byId("stat-usuarios").textContent = (data.usuarios || 0).toLocaleString("pt-BR");
      byId("stat-comandos").textContent = (data.comandos_total || 0).toLocaleString("pt-BR");
      byId("stat-ping").textContent = `${data.ultimo_ping || 0}ms`;
      byId("last-seen").textContent = data.last_seen
        ? `Última atualização: ${data.last_seen}`
        : (online ? "Patinho conectado à comunidade" : "Aguardando o Patinho conectar");
      byId("status-orb").classList.toggle("online", online);
    } catch (error) {
      byId("stat-online").textContent = "indisponível";
      byId("last-seen").textContent = "Não foi possível consultar o status agora.";
    }
  }

  let rankingAtual = "xp";
  const escapeHtml = (value) => String(value || "Morador").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;"
  }[char]));

  function medalha(position) {
    if (position === 1) return "🥇";
    if (position === 2) return "🥈";
    if (position === 3) return "🥉";
    return String(position).padStart(2, "0");
  }

  async function carregarRanking(tipo) {
    rankingAtual = tipo;
    const body = byId("ranking-body");
    const col = byId("col-valor");
    col.textContent = tipo === "xp" ? "XP" : "Moedas";
    body.innerHTML = '<p class="loading">Atualizando placar…</p>';
    try {
      const response = await fetch(`/api/ranking/${tipo}`, { cache: "no-store" });
      if (!response.ok) throw new Error("ranking indisponível");
      const dados = await response.json();
      if (!Array.isArray(dados) || dados.length === 0) {
        body.innerHTML = '<p class="loading">Ainda não há moradores no placar. Que tal ser o primeiro? 🐤</p>';
        return;
      }
      body.innerHTML = dados.slice(0, 10).map((user, index) => {
        const name = escapeHtml(user.user_name || `Morador ${index + 1}`);
        const value = Number(tipo === "xp" ? user.xp : user.saldo) || 0;
        const avatar = `https://imaging.habblet.city/avatarimage?user=${encodeURIComponent(user.user_name || "Habblet")}&head_direction=3&headonly=1&size=s`;
        return `<div class="ranking-row">
          <span class="rank-place">${medalha(index + 1)}</span>
          <span class="rank-user"><img src="${avatar}" alt="" onerror="this.style.visibility='hidden'"><span>${name}</span></span>
          <span class="rank-value">${value.toLocaleString("pt-BR")}</span>
        </div>`;
      }).join("");
    } catch (error) {
      body.innerHTML = '<p class="loading">Não foi possível carregar o placar agora.</p>';
    }
  }

  document.querySelectorAll("[data-ranking]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-ranking]").forEach((tab) => tab.classList.remove("ativo"));
      button.classList.add("ativo");
      carregarRanking(button.dataset.ranking);
    });
  });

  const news = Array.from(document.querySelectorAll("[data-news]"));
  let newsIndex = 0;
  const counter = byId("news-counter");
  function showNews(index) {
    if (!news.length) return;
    newsIndex = (index + news.length) % news.length;
    counter.textContent = `${newsIndex + 1} de ${news.length}`;
    news.forEach((card, position) => card.classList.toggle("focus-news", position === newsIndex));
    const featured = news[newsIndex];
    featured.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }
  byId("news-prev")?.addEventListener("click", () => showNews(newsIndex - 1));
  byId("news-next")?.addEventListener("click", () => showNews(newsIndex + 1));

  byId("current-year").textContent = new Date().getFullYear();
  atualizarStatus();
  carregarRanking("xp");
  window.setInterval(atualizarStatus, 10000);
  window.setInterval(() => carregarRanking(rankingAtual), 45000);
})();
