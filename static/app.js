/**
 * Instagram Archiver — backend-driven runtime UI.
 */

'use strict';

const POST_TYPES = {
  photo: {
    label: 'Фото',
    icon: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
      <circle cx="8.5" cy="8.5" r="1.5"/>
      <polyline points="21 15 16 10 5 21"/>
    </svg>`,
  },
  video: {
    label: 'Видео',
    icon: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="23 7 16 12 23 17 23 7"/>
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
    </svg>`,
  },
  carousel: {
    label: 'Карусель',
    icon: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="2" y="3" width="20" height="14" rx="2"/>
      <path d="M8 21h8M12 17v4"/>
    </svg>`,
  },
  unknown: {
    label: 'Тип недоступен',
    icon: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="10"/>
      <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2-3 4"/>
      <path d="M12 17h.01"/>
    </svg>`,
  },
};

const INITIAL_POST_BATCH = 24;
const LOAD_MORE_BATCH = 24;
const MAX_PREVIEW_POSTS = 200;

const state = {
  currentProfile: null,
  currentPage: 'search',
  posts: [],
  selectedPosts: new Set(),
  previewPostIndex: -1,
  activeTab: 'posts',
  activeFilter: 'all',
  downloadMode: 'selected',
  postsCount: 30,
  options: {
    fullJson: true,
    images: false,
    videos: false,
    comments: false,
    zip: true,
  },
  isDownloading: false,
  downloadProgress: 0,
  searchHistory: [],
};

const apiRuntime = {
  setupChecked: false,
  currentJobId: null,
  pollTimer: null,
  profilePollTimer: null,
  secretFile: null,
  profileRequestSeq: 0,
  postsLoading: false,
  itemStatuses: new Map(),
};

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return number.toLocaleString('ru-RU');
}

function formatMetric(value) {
  return value === null || value === undefined ? '—' : formatNumber(value);
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function optionalNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parseInput(input) {
  let value = String(input || '').trim().toLowerCase();
  if (value.startsWith('@')) value = value.slice(1);
  const match = value.match(/instagram\.com\/([^/?#&\s]+)/);
  if (match) return match[1].replace(/^@/, '').replace(/\/+$/, '');
  return value.replace(/\/+$/, '');
}

function captionTags(caption) {
  return (caption || '').match(/#\w+/g) || [];
}

function apiDate(isoDate) {
  if (!isoDate) return '—';
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showPage(pageId) {
  document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
  const page = document.getElementById(pageId === 'search' ? 'search-page' : 'profile-page');
  if (page) page.classList.add('active');
  state.currentPage = pageId;
}

function showToast(message, type = 'ok') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icons = {
    ok: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2"><path d="M9 12l2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>`,
    warn: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--orange)" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    err: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
  };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `${icons[type] || ''}<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function apiErrorMessage(data, status) {
  if (data?.error_code || data?.message) {
    return data.message || data.error_code || `HTTP ${status}`;
  }
  const detail = data?.detail || data?.error;
  if (Array.isArray(detail)) {
    return detail.map(item => item.msg || item.message || String(item)).join('; ');
  }
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || detail.error_code || JSON.stringify(detail);
  }
  return detail || `HTTP ${status}`;
}

async function apiRequest(path, options = {}) {
  const request = {
    credentials: 'include',
    ...options,
  };
  if (request.body && !(request.body instanceof FormData)) {
    request.headers = { 'Content-Type': 'application/json', ...(request.headers || {}) };
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(path, request);
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const error = new Error(apiErrorMessage(data, response.status));
    error.status = response.status;
    error.errorCode = data?.error_code || data?.detail?.error_code || null;
    error.retryAfter = data?.retry_after || data?.detail?.retry_after || null;
    throw error;
  }
  return data;
}

function normalizeApiError(error) {
  const message = error.message || 'Ошибка API';
  const code = error.errorCode || '';
  if (message.includes('Добавьте и проверьте Instagram account')) {
    openAccountsDrawer();
    return 'Добавьте Instagram account в панели Аккаунты.';
  }
  if (['LOGIN_REQUIRED', 'INVALID_SESSION', 'CHECKPOINT_REQUIRED'].includes(code) || message.startsWith('LOGIN_REQUIRED') || message.startsWith('CHECKPOINT_REQUIRED')) {
    openAccountsDrawer();
    return 'Instagram session недействительна или требует подтверждения. Обновите account в панели Аккаунты.';
  }
  if (code === 'SESSION_COOKIE_MISSING' || message.startsWith('SESSION_COOKIE_MISSING')) {
    openAccountsDrawer();
    return 'Instagram не выдал sessionid. Подтвердите вход в Instagram и повторите.';
  }
  if (code === 'COOKIES_FORMAT_UNKNOWN' || message.startsWith('COOKIES_FORMAT_UNKNOWN') || message.startsWith('SESSION_FILE_REQUIRED')) {
    openAccountsDrawer();
    return 'Instagram session недействительна. Обновите cookies/session в панели Аккаунты.';
  }
  if (code === 'TWO_FACTOR_REQUIRED' || message.startsWith('TWO_FACTOR_REQUIRED')) {
    document.getElementById('new-account-2fa')?.focus();
    return 'Instagram запросил 2FA-код. Введите код и нажмите “Добавить” ещё раз.';
  }
  if (code === 'BAD_CREDENTIALS' || message.startsWith('BAD_CREDENTIALS') || message.startsWith('LOGIN_FAILED')) {
    return 'Instagram не принял логин или пароль.';
  }
  if (code === 'RATE_LIMIT' || message.startsWith('RATE_LIMIT')) {
    return 'Instagram временно ограничил запросы. Подождите и попробуйте снова.';
  }
  if (code === 'PROFILE_NOT_FOUND' || message.startsWith('PROFILE_NOT_FOUND') || error.status === 404) {
    return 'Профиль Instagram не найден. Проверьте username или ссылку.';
  }
  if (code === 'NETWORK_ERROR' || code === 'TIMEOUT' || message.startsWith('NETWORK_ERROR') || message.includes('403 Forbidden')) {
    return 'Instagram временно отклоняет запрос. Попробуйте позже или обновите session.';
  }
  if (code === 'ADMIN_UNAUTHORIZED' || error.status === 401) {
    openLoginOverlay();
    return 'Нужен вход администратора';
  }
  if (error.status === 503) {
    openLoginOverlay();
    return 'Сервис ещё запускается. PostgreSQL и миграции поднимаются автоматически.';
  }
  return message;
}

function initialsFromUsername(username) {
  return (username || 'IG').slice(0, 2).toUpperCase();
}

function normalizeBio(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  return String(value || '').split('\n').map(line => line.trim()).filter(Boolean);
}

function mapApiProfile(payload) {
  const profile = payload.profile || payload;
  const username = profile.username || 'unknown';
  const followersCount = optionalNumber(profile.followers_count ?? profile.followers);
  const followingCount = optionalNumber(profile.following_count ?? profile.following);
  const postsCount = safeNumber(profile.posts_count, Array.isArray(profile.posts) ? profile.posts.length : 0);
  const source = payload.source || (payload.from_cache ? 'cache' : 'fresh');
  return {
    username,
    fullname: profile.full_name || profile.fullname || username,
    initials: initialsFromUsername(username),
    avatarUrl: profile.profile_pic_url || null,
    bio: normalizeBio(profile.bio ?? profile.biography),
    externalUrl: profile.external_url || null,
    postsCount,
    followersCount,
    followingCount,
    followers: formatMetric(followersCount),
    verified: Boolean(profile.is_verified),
    isPrivate: Boolean(profile.is_private),
    type: profile.is_private ? 'Приватный' : 'Публичный',
    since: source === 'cache' ? 'Превью из кэша' : 'Свежие данные Instagram',
    category: profile.is_private ? 'Private profile' : 'Instagram profile',
    raw: profile,
  };
}

function mapApiPost(post) {
  const apiType = post.type === 'image' ? 'photo' : post.type;
  const allowedTypes = ['photo', 'video', 'carousel', 'unknown'];
  const type = allowedTypes.includes(apiType) ? apiType : (post.is_video ? 'video' : 'unknown');
  const caption = post.caption || '';
  const shortcode = typeof post.shortcode === 'string' ? post.shortcode : '';
  return {
    id: shortcode,
    type,
    shortcode,
    likes: optionalNumber(post.likes),
    comments: optionalNumber(post.comments),
    format: post.format || (type === 'video' ? 'MP4' : 'JPEG'),
    resolution: post.resolution || '—',
    fileSize: post.file_size || post.fileSize || '—',
    location: post.location || null,
    date: apiDate(post.date),
    rawDate: post.date || null,
    caption,
    hashtags: captionTags(caption),
    carouselCount: type === 'carousel' ? Math.max(1, safeNumber(post.carousel_count, 1)) : 1,
    previewUrl: post.preview_url || post.url || null,
    raw: post,
  };
}

function mapApiPosts(posts) {
  return (Array.isArray(posts) ? posts : [])
    .map(mapApiPost)
    .filter(post => post.shortcode);
}

function syncSelectionWithPosts() {
  const available = new Set(state.posts.map(post => post.shortcode));
  state.selectedPosts = new Set([...state.selectedPosts].filter(shortcode => available.has(shortcode)));
}

let liveLoaderTimer = null;

function showLiveLoader(username) {
  const overlay = document.getElementById('profile-loader');
  const primaryText = document.getElementById('loader-primary-text');
  const secondaryText = document.getElementById('loader-secondary-text');
  const steps = ['ls-1', 'ls-2', 'ls-3'];
  clearTimeout(liveLoaderTimer);
  clearInterval(apiRuntime.profilePollTimer);
  apiRuntime.profilePollTimer = null;
  overlay?.classList.add('visible');
  if (primaryText) primaryText.textContent = `Загружаем @${username}...`;
  if (secondaryText) secondaryText.textContent = 'Ожидаем backend progress';
  steps.forEach(id => document.getElementById(id)?.classList.remove('active', 'done'));
  document.getElementById('ls-1')?.classList.add('active');
}

function hideLiveLoader() {
  clearTimeout(liveLoaderTimer);
  clearInterval(apiRuntime.profilePollTimer);
  liveLoaderTimer = null;
  apiRuntime.profilePollTimer = null;
  document.getElementById('profile-loader')?.classList.remove('visible');
}

function updateProfileIndexLoader(job) {
  const primaryText = document.getElementById('loader-primary-text');
  const secondaryText = document.getElementById('loader-secondary-text');
  const stage = job.stage || 'prepare_session';
  const stageOrder = ['prepare_session', 'validate_session', 'fetch_profile', 'fetch_posts', 'save_index', 'done'];
  const activeIndex = Math.max(0, stageOrder.indexOf(stage));
  const stepForStage = stage === 'prepare_session' || stage === 'validate_session'
    ? 0
    : (stage === 'fetch_profile' ? 1 : 2);
  ['ls-1', 'ls-2', 'ls-3'].forEach((id, index) => {
    const element = document.getElementById(id);
    element?.classList.toggle('done', index < stepForStage || job.status === 'done');
    element?.classList.toggle('active', index === stepForStage && !['done', 'failed', 'cancelled'].includes(job.status));
  });
  const pct = Number(job.percent || 0);
  const countText = Number(job.total || 0) > 0 ? ` · ${job.current || 0}/${job.total}` : '';
  if (primaryText) primaryText.textContent = job.stage_label || stage;
  if (secondaryText) secondaryText.textContent = `${pct}%${countText}${job.current_item ? ' · ' + job.current_item : ''}`;
  if (activeIndex >= 0 && job.status === 'failed' && secondaryText) {
    secondaryText.textContent = `${job.error_code || 'ERROR'} · ${job.error_message || 'Ошибка индексации'}`;
  }
}

function setSearchBusy(busy) {
  const button = document.getElementById('btn-search');
  const text = button?.querySelector('.btn-search-text');
  if (!button || !text) return;
  button.disabled = busy;
  text.textContent = busy ? 'Загружаем...' : 'Загрузить профиль';
}

async function loadProfile(rawInput, options = {}) {
  const username = parseInput(rawInput);
  if (!username) {
    showToast('Введите username или ссылку на профиль', 'warn');
    return;
  }

  const requestSeq = apiRuntime.profileRequestSeq + 1;
  apiRuntime.profileRequestSeq = requestSeq;
  try {
    setSearchBusy(true);
    showLiveLoader(username);
    const started = await apiRequest('/api/profile/index/start', {
      method: 'POST',
      body: {
        target: username,
        limit: options.limit || INITIAL_POST_BATCH,
        force_refresh: Boolean(options.forceRefresh),
      },
    });
    const status = await pollProfileIndex(started.job_id, requestSeq);
    if (requestSeq !== apiRuntime.profileRequestSeq) return;
    const result = status.result || {};
    const profilePayload = {
      ok: true,
      source: 'fresh',
      profile: {
        ...(result.profile || {}),
        posts: result.posts || [],
      },
    };
    const profileData = mapApiProfile(profilePayload);
    state.currentProfile = profileData;
    state.posts = mapApiPosts(result.posts);
    state.selectedPosts.clear();
    apiRuntime.itemStatuses = new Map();
    state.activeTab = 'posts';
    state.activeFilter = 'all';
    apiRuntime.lastPreview = profilePayload;
    apiRuntime.postsLoading = false;
    addToHistory(profileData.username);
    renderProfile(profileData);
    showPage('profile');
    const freshness = document.querySelector('.freshness-text');
    if (freshness) freshness.textContent = 'Индекс загружен backend job';
    showToast(`Индекс @${profileData.username} готов`, 'ok');
  } catch (error) {
    if (requestSeq === apiRuntime.profileRequestSeq) showToast(normalizeApiError(error), 'err');
    apiRuntime.postsLoading = false;
  } finally {
    if (requestSeq === apiRuntime.profileRequestSeq) {
      hideLiveLoader();
      setSearchBusy(false);
    }
  }
}

async function pollProfileIndex(jobId, requestSeq) {
  if (!jobId) throw new Error('Backend не вернул job_id');
  clearInterval(apiRuntime.profilePollTimer);
  return new Promise((resolve, reject) => {
    let stopped = false;
    const stop = () => {
      stopped = true;
      clearInterval(apiRuntime.profilePollTimer);
      apiRuntime.profilePollTimer = null;
    };
    const tick = async () => {
      try {
        if (requestSeq !== apiRuntime.profileRequestSeq) {
          stop();
          reject(new Error('Запрос профиля был заменён новым'));
          return;
        }
        const job = await apiRequest(`/api/profile/index/${jobId}/status`);
        updateProfileIndexLoader(job);
        if (job.status === 'done') {
          stop();
          resolve(job);
        } else if (['failed', 'cancelled'].includes(job.status)) {
          const error = new Error(job.error_message || job.error_code || 'Ошибка индексации профиля');
          error.errorCode = job.error_code || null;
          stop();
          reject(error);
        }
      } catch (error) {
        stop();
        reject(error);
      }
    };
    tick();
    if (!stopped) apiRuntime.profilePollTimer = setInterval(tick, 1500);
  });
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function renderAvatar(profile) {
  const avatar = document.getElementById('profile-avatar');
  const initials = document.getElementById('profile-initials');
  if (!avatar || !initials) return;
  initials.textContent = profile.initials || initialsFromUsername(profile.username);
  avatar.classList.remove('profile-avatar-has-image');
  let image = avatar.querySelector('.profile-avatar-img');
  if (!image) {
    image = document.createElement('img');
    image.className = 'profile-avatar-img';
    image.alt = '';
    avatar.prepend(image);
  }
  image.removeAttribute('src');
  image.style.display = 'none';
}

function syncToolbarState() {
  document.querySelectorAll('.posts-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === state.activeTab);
  });
  document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.classList.toggle('active', chip.dataset.filter === state.activeFilter);
  });
}

function renderProfile(profile) {
  setText('bc-username', profile.username);
  renderAvatar(profile);
  const verifiedBadge = document.querySelector('.verified-badge');
  if (verifiedBadge) verifiedBadge.style.display = profile.verified ? 'flex' : 'none';
  setText('profile-fullname', profile.fullname || profile.username);
  setText('profile-username', `@${profile.username}`);
  setText('stat-posts', safeNumber(profile.postsCount, 0).toLocaleString('ru-RU'));
  setText('stat-followers', profile.followers || formatMetric(profile.followersCount));
  setText('stat-following', formatMetric(profile.followingCount));
  const typeBadge = document.querySelector('.profile-type-badge');
  if (typeBadge) typeBadge.textContent = profile.type || (profile.isPrivate ? 'Приватный' : 'Публичный');

  const bioEl = document.getElementById('profile-bio');
  if (bioEl) {
    bioEl.innerHTML = '';
    if (profile.bio.length) {
      profile.bio.forEach(line => {
        const p = document.createElement('p');
        p.textContent = line;
        bioEl.appendChild(p);
      });
    } else {
      const p = document.createElement('p');
      p.textContent = 'Описание профиля недоступно через текущий API.';
      bioEl.appendChild(p);
    }
    if (profile.externalUrl) {
      const link = document.createElement('a');
      link.className = 'bio-link';
      link.href = profile.externalUrl.startsWith('http') ? profile.externalUrl : `https://${profile.externalUrl}`;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = profile.externalUrl.replace(/^https?:\/\//, '');
      bioEl.appendChild(link);
    }
  }

  const metaRows = document.querySelectorAll('.profile-meta .meta-row span');
  if (metaRows[0]) metaRows[0].textContent = profile.since || 'Данные backend';
  if (metaRows[1]) metaRows[1].textContent = profile.category || 'Instagram profile';
  syncToolbarState();
  renderStories();
  renderPostsGrid();
  updateEstimate();
}

function renderStories() {
  const container = document.getElementById('stories-scroll');
  if (!container) return;
  container.innerHTML = '<div class="story-empty-state"><span>Highlights недоступны через текущий API</span></div>';
  setText('stories-count', '0 highlights');
}

function getFilteredPosts() {
  let posts = state.posts;
  if (state.activeTab === 'reels') {
    posts = posts.filter(post => post.type === 'video');
  } else if (state.activeTab === 'tagged') {
    posts = [];
  }
  if (state.activeFilter !== 'all') posts = posts.filter(post => post.type === state.activeFilter);
  return posts;
}

function postsEmptyMessage() {
  if (apiRuntime.postsLoading) return 'Загружаем публикации...';
  if (state.activeTab === 'tagged') return 'Отмеченные публикации недоступны через текущий API.';
  if (state.activeTab === 'reels') return 'Видео/Reels не найдены в загруженном preview.';
  if (state.activeFilter !== 'all') return 'Для выбранного фильтра нет публикаций в текущем preview.';
  return 'Backend не вернул публикации для этого профиля.';
}

function renderPostsGrid() {
  const grid = document.getElementById('posts-grid');
  if (!grid) return;
  grid.innerHTML = '';
  const posts = getFilteredPosts();
  grid.classList.toggle('posts-grid-empty', posts.length === 0);
  if (!posts.length) {
    const empty = document.createElement('div');
    empty.className = 'posts-empty-state';
    empty.textContent = postsEmptyMessage();
    grid.appendChild(empty);
  } else {
    posts.forEach((post, index) => grid.appendChild(createPostCard(post, index)));
  }
  updateSelectedCounter();

  const gridEnd = document.getElementById('grid-end');
  if (!gridEnd) return;
  if (!state.currentProfile) {
    gridEnd.style.display = 'none';
    return;
  }
  gridEnd.style.display = 'flex';
  setText('total-loaded', state.posts.length);
  const totalEl = gridEnd.querySelector('span strong:last-child');
  const total = safeNumber(state.currentProfile?.postsCount, state.posts.length);
  if (totalEl) totalEl.textContent = total.toLocaleString('ru-RU');
  const loadMore = document.getElementById('btn-load-more');
  if (loadMore) {
    const previewTotal = Math.min(total, MAX_PREVIEW_POSTS);
    const canLoadMore = state.activeTab === 'posts' && state.activeFilter === 'all' && state.posts.length < previewTotal;
    loadMore.style.display = canLoadMore ? 'inline-flex' : 'none';
    loadMore.textContent = `Загрузить ещё ${LOAD_MORE_BATCH}`;
  }
}

function createPostCard(post, index) {
  const card = document.createElement('div');
  const selected = state.selectedPosts.has(post.shortcode);
  const typeInfo = POST_TYPES[post.type] || POST_TYPES.unknown;
  const itemStatus = apiRuntime.itemStatuses.get(post.shortcode) || {};
  const statusChips = ['full_json_status', 'image_status', 'video_status', 'comments_status']
    .map(key => {
      const value = itemStatus[key];
      if (!value || value === 'skipped') return '';
      const label = {
        full_json_status: 'JSON',
        image_status: 'IMG',
        video_status: 'VID',
        comments_status: 'COM',
      }[key];
      return `<span class="post-stage-chip post-stage-${escapeHtml(value)}">${label}:${escapeHtml(value)}</span>`;
    })
    .join('');
  card.className = `post-card${selected ? ' selected' : ''}`;
  card.dataset.postId = post.shortcode;
  card.dataset.postIndex = String(index);
  card.innerHTML = `
    <div class="post-media-shell">
      <div class="post-image-fallback metadata-card">
        <strong>${escapeHtml(post.shortcode)}</strong>
        <span>${escapeHtml(post.date || '—')}</span>
        <p>${escapeHtml((post.caption || 'Caption недоступен').slice(0, 92))}</p>
        ${statusChips ? `<div class="post-stage-chips">${statusChips}</div>` : ''}
      </div>
    </div>
    <div class="post-type-icon" title="${escapeHtml(typeInfo.label)}">${typeInfo.icon}</div>
    <div class="post-checkbox-wrap">
      <input type="checkbox" class="post-checkbox" ${selected ? 'checked' : ''} />
    </div>
    <div class="post-overlay">
      <div class="post-overlay-stats">
        <div class="overlay-stat">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
          ${formatMetric(post.likes)}
        </div>
        <div class="overlay-stat">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          ${formatMetric(post.comments)}
        </div>
      </div>
    </div>
  `;
  card.addEventListener('click', event => {
    if (event.target.classList.contains('post-checkbox')) return;
    openPostPreview(index);
  });
  card.querySelector('.post-checkbox')?.addEventListener('change', event => {
    event.stopPropagation();
    togglePostSelection(post.shortcode, card, event.target.checked);
  });
  return card;
}

function togglePostSelection(shortcode, card, selected) {
  if (selected) {
    state.selectedPosts.add(shortcode);
    card?.classList.add('selected');
  } else {
    state.selectedPosts.delete(shortcode);
    card?.classList.remove('selected');
  }
  updateSelectedCounter();
  updateEstimate();
}

function updateSelectedCounter() {
  setText('selected-count', state.selectedPosts.size);
}

function syncPostSelectionUi(shortcode, selected) {
  document.querySelectorAll('.post-card').forEach(card => {
    if (card.dataset.postId !== shortcode) return;
    card.classList.toggle('selected', selected);
    const checkbox = card.querySelector('.post-checkbox');
    if (checkbox) checkbox.checked = selected;
  });
  const previewCheckbox = document.getElementById('preview-post-checkbox');
  const posts = getFilteredPosts();
  if (posts[state.previewPostIndex]?.shortcode === shortcode && previewCheckbox) {
    previewCheckbox.checked = selected;
  }
}

function addPostToSelection(post, message) {
  if (!post?.shortcode) return;
  state.selectedPosts.add(post.shortcode);
  syncPostSelectionUi(post.shortcode, true);
  updateSelectedCounter();
  updateEstimate();
  showToast(message || `Пост ${post.shortcode} добавлен в выборку`, 'ok');
}

function openPostPreview(index) {
  const posts = getFilteredPosts();
  if (index < 0 || index >= posts.length) return;
  state.previewPostIndex = index;
  const post = posts[index];
  const typeInfo = POST_TYPES[post.type] || POST_TYPES.unknown;

  setText('preview-author-avatar', state.currentProfile?.initials || initialsFromUsername(state.currentProfile?.username || 'IG'));
  setText('preview-author-name', state.currentProfile?.username || 'unknown');
  setText('preview-post-date', post.date || '—');
  setText('preview-likes', formatMetric(post.likes));
  setText('preview-comments-count', formatMetric(post.comments));
  setText('preview-type-label', typeInfo.label);
  setText('preview-post-id', post.shortcode);

  const mediaType = document.getElementById('preview-media-type');
  if (mediaType) {
    mediaType.innerHTML = `${typeInfo.icon}<span>${escapeHtml(typeInfo.label)}</span>`;
    mediaType.style.display = 'flex';
  }
  const content = document.getElementById('preview-media-content');
  if (content) {
    content.innerHTML = `
      <div class="preview-fallback metadata-preview">
        <strong>${escapeHtml(post.shortcode)}</strong>
        <span>${escapeHtml(typeInfo.label)} · ${escapeHtml(post.date || '—')}</span>
        <p>${escapeHtml(post.caption || 'Caption недоступен.')}</p>
      </div>
    `;
  }

  const captionEl = document.getElementById('preview-caption');
  if (captionEl) {
    captionEl.textContent = post.caption || 'Caption недоступен.';
    captionEl.classList.remove('expanded');
  }
  setText('caption-toggle', 'Читать полностью');

  const hashEl = document.getElementById('preview-hashtags');
  if (hashEl) {
    hashEl.innerHTML = '';
    post.hashtags.forEach(tag => {
      const chip = document.createElement('span');
      chip.className = 'hashtag-chip';
      chip.textContent = tag;
      hashEl.appendChild(chip);
    });
  }

  const locationEl = document.getElementById('preview-location');
  if (locationEl) {
    if (post.location) {
      locationEl.style.display = 'flex';
      setText('preview-location-text', post.location);
    } else {
      locationEl.style.display = 'none';
    }
  }

  setText('pm-shortcode', post.shortcode);
  setText('pm-resolution', post.resolution || '—');
  setText('pm-format', post.format || '—');
  setText('pm-size', post.fileSize || '—');
  setText('pm-timestamp', post.rawDate || post.date || '—');

  const dotsContainer = document.getElementById('carousel-dots');
  if (dotsContainer) {
    dotsContainer.innerHTML = '';
    if (post.type === 'carousel' && post.carouselCount > 1) {
      for (let i = 0; i < post.carouselCount; i += 1) {
        const dot = document.createElement('div');
        dot.className = `carousel-dot${i === 0 ? ' active' : ''}`;
        dotsContainer.appendChild(dot);
      }
    }
  }

  const checkbox = document.getElementById('preview-post-checkbox');
  if (checkbox) checkbox.checked = state.selectedPosts.has(post.shortcode);
  document.getElementById('post-preview-overlay')?.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closePostPreview() {
  document.getElementById('post-preview-overlay')?.classList.remove('open');
  document.body.style.overflow = '';
  state.previewPostIndex = -1;
}

function navigatePreview(direction) {
  const posts = getFilteredPosts();
  const nextIndex = state.previewPostIndex + direction;
  if (nextIndex >= 0 && nextIndex < posts.length) openPostPreview(nextIndex);
}

function setDownloadMode(mode) {
  state.downloadMode = mode;
  document.querySelectorAll('input[name="dl-mode"]').forEach(radio => {
    radio.checked = radio.value === mode;
  });
  document.querySelectorAll('.mode-card').forEach(card => card.classList.remove('active'));
  const activeCard = document.querySelector(`input[name="dl-mode"][value="${mode}"]`)?.closest('.mode-option')?.querySelector('.mode-card');
  activeCard?.classList.add('active');
  const paramEl = document.getElementById('param-last-n');
  if (paramEl) paramEl.style.display = mode === 'last-n' ? 'block' : 'none';
  updateEstimate();
}

function updateEstimate() {
  const count = state.selectedPosts.size;
  const selectedPosts = state.posts.filter(post => state.selectedPosts.has(post.shortcode));
  const imageCount = state.options.images ? selectedPosts.filter(post => ['photo', 'carousel'].includes(post.type)).length : 0;
  const videoCount = state.options.videos ? selectedPosts.filter(post => ['video', 'reel'].includes(post.type)).length : 0;
  const totalFiles = imageCount + videoCount + (state.options.fullJson ? count : 0) + (state.options.comments ? count : 0);
  const totalMb = imageCount * 4 + videoCount * 18;
  setText('est-posts', count > 0 ? count.toLocaleString('ru-RU') : '—');
  setText('est-files', totalFiles > 0 ? `~${totalFiles}` : '—');
  setText('est-size', totalMb > 0 ? `~${totalMb} MB` : '< 1 MB');
}

async function startDownload() {
  if (state.isDownloading) return;
  if (!state.currentProfile) {
    showToast('Сначала загрузите профиль', 'warn');
    return;
  }
  if (state.selectedPosts.size === 0) {
    showToast('Выберите хотя бы один пост для скачивания', 'warn');
    return;
  }
  if (!state.options.fullJson && !state.options.images && !state.options.videos && !state.options.comments && !state.options.zip) {
    showToast('Включите хотя бы одну задачу', 'warn');
    return;
  }
  const progressBlock = document.getElementById('progress-block');
  const startBtn = document.getElementById('btn-start-download');
  const downloadZipBtn = document.getElementById('btn-download-zip');
  try {
    state.isDownloading = true;
    state.downloadProgress = 0;
    if (progressBlock) progressBlock.style.display = 'flex';
    if (downloadZipBtn) downloadZipBtn.style.display = 'none';
    if (startBtn) {
      startBtn.textContent = 'Создаём задачу...';
      startBtn.style.opacity = '0.5';
      startBtn.style.pointerEvents = 'none';
    }
    const progressBar = document.getElementById('progress-bar');
    if (progressBar) {
      progressBar.style.width = '0%';
      progressBar.style.background = 'var(--orange)';
    }
    const job = await apiRequest('/api/jobs/create', {
      method: 'POST',
      body: {
        target: state.currentProfile.username,
        shortcodes: Array.from(state.selectedPosts),
        tasks: {
          full_json: state.options.fullJson,
          images: state.options.images,
          videos: state.options.videos,
          comments: state.options.comments,
          zip: state.options.zip,
        },
      },
    });
    apiRuntime.currentJobId = job.id || job.job_id;
    updateJobProgress(job);
    pollJob(apiRuntime.currentJobId);
    refreshJobsHistory();
  } catch (error) {
    state.isDownloading = false;
    restoreStartButton();
    showToast(normalizeApiError(error), 'err');
  }
}

async function pollJob(jobId) {
  if (!jobId) return;
  clearInterval(apiRuntime.pollTimer);
  let stopped = false;
  const tick = async () => {
    try {
      const job = await apiRequest(`/api/jobs/${jobId}/status`);
      updateJobProgress(job);
      await refreshJobsHistory();
      if (['done', 'failed', 'cancelled'].includes(job.status)) {
        stopped = true;
        clearInterval(apiRuntime.pollTimer);
        apiRuntime.pollTimer = null;
      }
    } catch (error) {
      stopped = true;
      clearInterval(apiRuntime.pollTimer);
      apiRuntime.pollTimer = null;
      showToast(normalizeApiError(error), 'err');
    }
  };
  await tick();
  if (!stopped) apiRuntime.pollTimer = setInterval(tick, 2500);
}

function updateJobProgress(job) {
  const overall = job.overall || {};
  const total = Number(overall.total || job.items_total || 0);
  const done = Number(overall.current || job.items_done || job.completed_items || 0);
  const pct = Number.isFinite(Number(overall.percent)) ? Number(overall.percent) : (total ? Math.min(100, Math.round((done / total) * 100)) : 0);
  state.downloadProgress = pct;
  setText('progress-pct', `${pct}%`);
  setText('progress-current', done);
  setText('progress-total', total || 0);
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) progressBar.style.width = `${pct}%`;
  setText('progress-label', job.stage_label || job.status);
  setText('progress-current-item', job.current_item || '—');
  renderStageProgress(job.stages || {});
  renderJobItemStatuses(job.items || []);
  const rateLimit = document.getElementById('rate-limit-warn');
  if (rateLimit) rateLimit.style.display = job.status === 'waiting' ? 'flex' : 'none';
  if (job.status === 'done') {
    state.isDownloading = false;
    if (progressBar) progressBar.style.background = 'var(--green)';
    const downloadZipBtn = document.getElementById('btn-download-zip');
    if (downloadZipBtn) downloadZipBtn.style.display = job.archive_ready ? 'flex' : 'none';
    const zipSize = document.querySelector('.zip-size');
    if (zipSize) zipSize.textContent = formatBytes(job.archive_size_bytes);
    restoreStartButton();
    showToast('Архивирование завершено успешно!', 'ok');
  } else if (job.status === 'failed' || job.status === 'cancelled') {
    state.isDownloading = false;
    restoreStartButton();
    showToast(job.error_message || job.failure_reason || 'Ошибка архивации', 'err');
  } else if (job.status === 'waiting') {
    state.isDownloading = false;
    restoreStartButton();
  }
}

function renderStageProgress(stages) {
  const container = document.getElementById('stage-progress-list');
  if (!container) return;
  const labels = {
    full_json: 'JSON',
    images: 'Изображения',
    videos: 'Видео',
    comments: 'Комментарии',
    zip: 'ZIP',
  };
  container.innerHTML = Object.entries(stages)
    .filter(([, stage]) => stage.enabled)
    .map(([name, stage]) => {
      const total = Number(stage.total || 0);
      const current = Number(stage.current || 0);
      const pct = total ? Math.round((current / total) * 100) : (stage.status === 'done' ? 100 : 0);
      return `
        <div class="stage-progress-row">
          <span>${escapeHtml(labels[name] || name)}</span>
          <div class="stage-progress-bar"><i style="width:${pct}%"></i></div>
          <b>${escapeHtml(stage.status || 'queued')} · ${current}/${total}</b>
        </div>
      `;
    })
    .join('');
}

function renderJobItemStatuses(items) {
  apiRuntime.itemStatuses = new Map((items || []).map(item => [item.shortcode, item]));
  renderPostsGrid();
  const errorList = document.getElementById('item-error-list');
  if (!errorList) return;
  const failed = (items || []).filter(item => item.error_code || item.error_message);
  errorList.innerHTML = failed.slice(0, 5).map(item => `
    <div class="item-error-row">
      <span>${escapeHtml(item.shortcode)}</span>
      <b>${escapeHtml(item.error_code || 'ERROR')}</b>
    </div>
  `).join('');
}

function restoreStartButton() {
  const startBtn = document.getElementById('btn-start-download');
  if (!startBtn) return;
  startBtn.textContent = 'Начать догрузку';
  startBtn.style.opacity = '1';
  startBtn.style.pointerEvents = 'auto';
}

function pauseDownload() {
  showToast('Пауза через API пока недоступна; задача продолжает выполняться.', 'warn');
}

function stopDownload() {
  clearInterval(apiRuntime.pollTimer);
  apiRuntime.pollTimer = null;
  state.isDownloading = false;
  restoreStartButton();
  showToast('Остановлен только локальный опрос. Backend-задача продолжает выполняться.', 'warn');
}

function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes)) || Number(bytes) <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = Number(bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function addToHistory(username) {
  state.searchHistory = state.searchHistory.filter(item => item !== username);
  state.searchHistory.unshift(username);
  state.searchHistory = state.searchHistory.slice(0, 5);
  renderHistory();
}

function renderHistory() {
  const list = document.getElementById('recent-list');
  if (!list) return;
  list.innerHTML = '';
  if (!state.searchHistory.length) {
    const empty = document.createElement('div');
    empty.className = 'recent-empty';
    empty.textContent = 'История появится после успешной загрузки профиля';
    list.appendChild(empty);
    return;
  }
  const timeLabels = ['только что', 'недавно', 'ранее', 'ранее', 'ранее'];
  state.searchHistory.forEach((username, index) => {
    const item = document.createElement('button');
    item.className = 'recent-item';
    item.innerHTML = `
      <span class="recent-icon">⏱</span>
      <span>${escapeHtml(username)}</span>
      <span class="recent-time">${timeLabels[index] || 'ранее'}</span>
    `;
    item.addEventListener('click', () => {
      const input = document.getElementById('search-input');
      if (input) input.value = username;
      loadProfile(username);
    });
    list.appendChild(item);
  });
}

function openSetupOverlay() {
  document.getElementById('setup-overlay')?.classList.add('open');
  document.getElementById('login-overlay')?.classList.remove('open');
}

function closeSetupOverlay() {
  document.getElementById('setup-overlay')?.classList.remove('open');
}

function openLoginOverlay() {
  document.getElementById('login-overlay')?.classList.add('open');
  document.getElementById('setup-overlay')?.classList.remove('open');
}

function closeLoginOverlay() {
  document.getElementById('login-overlay')?.classList.remove('open');
}

async function bootstrapAuthState() {
  try {
    const status = await apiRequest('/api/setup/status');
    apiRuntime.setupChecked = true;
    if (!status.configured || !status.database_connected) {
      openLoginOverlay();
      if (status.error) showToast(status.error, 'warn');
      return;
    }
    if (!status.needs_login) {
      openSetupOverlay();
      return;
    }
    const me = await apiRequest('/api/auth/me');
    closeSetupOverlay();
    closeLoginOverlay();
    const badge = document.querySelector('.session-badge');
    if (badge) badge.textContent = me.username || 'admin';
    await Promise.allSettled([loadAccountsFromApi(), loadSettingsIntoForm(), refreshJobsHistory()]);
  } catch (error) {
    if (error.status === 401) {
      openLoginOverlay();
    } else {
      showToast(normalizeApiError(error), 'warn');
    }
  }
}

function openAccountsDrawer() {
  document.getElementById('accounts-drawer-overlay')?.classList.add('open');
  renderAccountsLoading();
  loadAccountsFromApi();
}

function closeAccountsDrawer() {
  document.getElementById('accounts-drawer-overlay')?.classList.remove('open');
}

function renderAccountsLoading() {
  const list = document.getElementById('accounts-list');
  if (!list) return;
  list.innerHTML = `
    <div class="account-card account-loading">
      <div class="account-avatar">IG</div>
      <div class="account-info">
        <div class="account-name-row">
          <span class="account-username">Загрузка аккаунтов...</span>
          <span class="account-status-badge account-warning">vault</span>
        </div>
        <div class="account-details">
          <div class="account-detail-row">
            <span class="detail-key">Secret</span>
            <span class="detail-val">Содержимое session/cookies никогда не показывается</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function loadAccountsFromApi() {
  try {
    const accounts = await apiRequest('/api/accounts');
    renderAccountsDrawer(accounts || []);
  } catch (error) {
    if (error.status !== 401 && error.status !== 503) showToast(normalizeApiError(error), 'warn');
  }
}

function renderAccountsDrawer(accounts) {
  const list = document.getElementById('accounts-list');
  if (!list) return;
  list.innerHTML = '';
  document.querySelectorAll('.accounts-badge').forEach(badge => {
    badge.textContent = accounts.length;
  });
  if (!accounts.length) {
    list.innerHTML = `
      <div class="account-card">
        <div class="account-avatar">IG</div>
        <div class="account-info">
          <div class="account-name-row">
            <span class="account-username">Нет аккаунтов</span>
            <span class="account-status-badge account-warning">нужны cookies</span>
          </div>
          <div class="account-details">
            <div class="account-detail-row">
              <span class="detail-key">Vault</span>
              <span class="detail-val">Загрузите browser cookies или settings файл</span>
            </div>
          </div>
        </div>
      </div>
    `;
    return;
  }
  accounts.forEach(account => {
    const ok = account.status === 'OK';
    const unsupported = account.session_kind === 'unsupported_legacy';
    const card = document.createElement('div');
    card.className = `account-card ${ok ? 'account-active' : 'account-warn'}`;
    card.innerHTML = `
      <div class="account-avatar">${escapeHtml(initialsFromUsername(account.username))}</div>
      <div class="account-info">
        <div class="account-name-row">
          <span class="account-username">@${escapeHtml(account.username)}</span>
          <span class="account-status-badge ${ok ? 'account-ok' : 'account-warning'}">${escapeHtml(account.status)}</span>
        </div>
        <div class="account-details">
          <div class="account-detail-row">
            <span class="detail-key">Session</span>
            <span class="detail-val ${unsupported ? 'detail-warn' : 'detail-ok'}">${escapeHtml(sessionKindLabel(account.session_kind))}</span>
          </div>
          <div class="account-detail-row">
            <span class="detail-key">Provider</span>
            <span class="detail-val">${escapeHtml(account.provider || 'instagram')}${account.is_default ? ' · default' : ''}</span>
          </div>
          <div class="account-detail-row">
            <span class="detail-key">Last OK</span>
            <span class="detail-val">${escapeHtml(apiDate(account.last_ok_at))}</span>
          </div>
          <div class="account-detail-row">
            <span class="detail-key">Last error</span>
            <span class="detail-val">${escapeHtml(account.last_error_reason || account.failure_reason || 'Нет')}${account.last_error_at ? ' · ' + escapeHtml(apiDate(account.last_error_at)) : ''}</span>
          </div>
          <div class="account-detail-row">
            <span class="detail-key">User-Agent</span>
            <span class="detail-val">${escapeHtml(shortUserAgent(account.user_agent))}</span>
          </div>
          ${unsupported ? '<div class="account-detail-row"><span class="detail-key">Note</span><span class="detail-val detail-warn">Загрузите cookies/settings заново</span></div>' : ''}
        </div>
      </div>
      <div class="account-actions">
        <button class="acc-btn acc-btn-default" data-action="default" title="Использовать по умолчанию">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
        </button>
        <button class="acc-btn" data-action="validate" title="Проверить сессию">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
        </button>
        <button class="acc-btn acc-btn-danger" data-action="delete" title="Удалить аккаунт">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
        </button>
      </div>
    `;
    card.querySelector('[data-action="default"]')?.addEventListener('click', async () => {
      await apiRequest(`/api/accounts/${account.id}/default`, { method: 'POST' });
      await loadAccountsFromApi();
    });
    card.querySelector('[data-action="validate"]')?.addEventListener('click', async () => {
      await apiRequest(`/api/accounts/${account.id}/validate`, { method: 'POST' });
      await loadAccountsFromApi();
    });
    card.querySelector('[data-action="delete"]')?.addEventListener('click', async () => {
      if (!confirm(`Удалить аккаунт @${account.username} из encrypted vault?`)) return;
      try {
        await apiRequest(`/api/accounts/${account.id}`, { method: 'DELETE' });
        await loadAccountsFromApi();
        showToast(`Аккаунт @${account.username} удалён`, 'ok');
      } catch (error) {
        showToast(normalizeApiError(error), 'err');
      }
    });
    list.appendChild(card);
  });
}

function sessionKindLabel(kind) {
  const labels = {
    browser_cookies: 'Browser cookie jar',
    instagrapi_settings: 'Instagrapi settings',
    unsupported_legacy: 'Unsupported old session',
  };
  return labels[kind] || kind || 'unknown';
}

function shortUserAgent(value) {
  if (!value) return '—';
  return value.length > 74 ? `${value.slice(0, 71)}...` : value;
}

async function uploadAccountSecret(event) {
  event.preventDefault();
  event.stopImmediatePropagation();
  const submit = document.getElementById('btn-confirm-add');
  const username = document.getElementById('new-account-username')?.value.trim() || '';
  const secretKindSelect = document.getElementById('new-account-secret-kind');
  const secretKind = secretKindSelect?.value || 'cookies';
  const secretValue = document.getElementById('new-account-secret-value')?.value.trim() || '';
  const inputFile = document.getElementById('session-file-input')?.files[0];
  const file = apiRuntime.secretFile || inputFile;

  if (!file && !secretValue) {
    showToast('Загрузите cookie/settings файл или вставьте cookie jar', 'warn');
    return;
  }
  if (!username && !secretValue) {
    showToast('Введите username или вставьте cookie jar строку', 'warn');
    document.getElementById('new-account-username')?.focus();
    return;
  }

  try {
    if (submit) {
      submit.disabled = true;
      submit.textContent = 'Проверяем...';
    }
    const formData = new FormData();
    if (username) formData.append('username', username);
    formData.append('secret_kind', secretKind);
    if (secretValue) {
      formData.append('secret_value', secretValue);
    } else {
      formData.append('secret_file', file);
    }
    const account = await apiRequest('/api/accounts', { method: 'POST', body: formData });
    resetAccountForm();
    await loadAccountsFromApi();
    showToast(`Аккаунт @${account.username} сохранён в encrypted vault`, 'ok');
  } catch (error) {
    showToast(normalizeApiError(error), 'err');
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = 'Добавить';
    }
  }
}

function resetAccountForm() {
  document.getElementById('add-account-form').style.display = 'none';
  ['new-account-username', 'new-account-secret-value'].forEach(id => {
    const element = document.getElementById(id);
    if (element) element.value = '';
  });
  const kind = document.getElementById('new-account-secret-kind');
  if (kind) kind.value = 'cookies';
  const fileInput = document.getElementById('session-file-input');
  if (fileInput) fileInput.value = '';
  apiRuntime.secretFile = null;
  resetDropZone();
}

function resetDropZone() {
  const dropZone = document.getElementById('session-drop-zone');
  if (!dropZone) return;
  dropZone.style.color = '';
  dropZone.innerHTML = `
    <input type="file" id="session-file-input" class="sr-only" />
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
    </svg>
    <span>Перетащите cookies/settings файл или <u>выберите</u></span>
  `;
  bindDropZoneFileInput();
  const advancedBlock = document.getElementById('advanced-secret-block');
  if (advancedBlock) advancedBlock.style.display = 'flex';
}

function bindDropZoneFileInput() {
  const dropZone = document.getElementById('session-drop-zone');
  const input = document.getElementById('session-file-input');
  if (!dropZone || !input) return;
  dropZone.onclick = () => input.click();
  input.addEventListener('change', () => {
    apiRuntime.secretFile = input.files[0] || null;
    if (apiRuntime.secretFile) {
      const label = dropZone.querySelector('span');
      if (label) label.textContent = `${apiRuntime.secretFile.name} (${(apiRuntime.secretFile.size / 1024).toFixed(1)} KB)`;
      dropZone.style.color = 'var(--green)';
    }
  });
}

async function loadSettingsIntoForm() {
  try {
    const data = await apiRequest('/api/settings');
    const form = document.getElementById('settings-form');
    Object.entries(data.settings || {}).forEach(([key, value]) => {
      if (form?.elements[key]) form.elements[key].value = value;
    });
    setText('db-size', 'PostgreSQL');
  } catch (error) {
    if (error.status !== 401 && error.status !== 503) showToast(normalizeApiError(error), 'warn');
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const form = document.getElementById('settings-form');
  if (!form) return;
  const settings = {};
  ['preview_cache_ttl_sec', 'rate_limit_wait_sec', 'scheduler_interval_sec', 'default_preview_posts', 'comments_limit'].forEach(key => {
    settings[key] = Number(form.elements[key].value);
  });
  settings.archive_dir = form.elements.archive_dir.value.trim();
  try {
    await apiRequest('/api/settings', { method: 'PUT', body: { settings } });
    showToast('Настройки сохранены', 'ok');
    document.getElementById('settings-overlay')?.classList.remove('open');
  } catch (error) {
    showToast(normalizeApiError(error), 'err');
  }
}

async function refreshJobsHistory() {
  try {
    const jobs = await apiRequest('/api/jobs');
    const list = document.querySelector('#jobs-history .jobs-list');
    if (!list) return;
    list.innerHTML = '';
    const visibleJobs = (jobs || []).filter(job => job.type !== 'profile_index').slice(0, 4);
    if (!visibleJobs.length) {
      list.innerHTML = `
        <div class="job-item">
          <div class="job-status-dot job-paused-dot"></div>
          <div class="job-info">
            <span class="job-name">Задач пока нет</span>
            <span class="job-date">Создайте архив после загрузки профиля</span>
          </div>
          <span class="job-size">—</span>
        </div>
      `;
      return;
    }
    visibleJobs.forEach(job => {
      const item = document.createElement('div');
      const dotClass = job.status === 'done' ? 'job-done-dot' : (job.status === 'failed' ? 'job-error-dot' : 'job-paused-dot');
      const archiveSize = job.archive_size_bytes ? formatBytes(job.archive_size_bytes) : `${job.items_done} / ${job.items_total}`;
      const actions = [];
      if (job.can_resume) actions.push('<button class="job-action-btn job-action-btn-primary" data-action="resume">Возобновить</button>');
      if (job.download_url) actions.push('<button class="job-action-btn" data-action="download">ZIP</button>');
      item.className = 'job-item';
      item.innerHTML = `
        <div class="job-status-dot ${dotClass}"></div>
        <div class="job-info">
          <span class="job-name">@${escapeHtml(job.username)}</span>
          <span class="job-date">${escapeHtml(job.status)}${job.failure_reason ? ' · ' + escapeHtml(job.failure_reason) : ''}${job.archive_filename ? ' · ' + escapeHtml(job.archive_filename) : ''}</span>
        </div>
        <span class="job-size">${escapeHtml(archiveSize)}</span>
        ${actions.length ? `<div class="job-actions">${actions.join('')}</div>` : ''}
      `;
      item.querySelector('[data-action="resume"]')?.addEventListener('click', async () => {
        try {
          const resumed = await apiRequest(`/api/jobs/${job.id}/resume`, { method: 'POST' });
          apiRuntime.currentJobId = resumed.id || resumed.job_id;
          pollJob(apiRuntime.currentJobId);
          showToast('Задача возобновлена', 'ok');
        } catch (error) {
          showToast(normalizeApiError(error), 'warn');
        }
      });
      item.querySelector('[data-action="download"]')?.addEventListener('click', () => {
        window.location.href = job.download_url;
      });
      list.appendChild(item);
    });
  } catch {
    // История задач не должна мешать экрану входа.
  }
}

function setFormBusy(form, busy, busyText) {
  if (!form) return;
  const submit = form.querySelector('button[type="submit"]');
  if (submit) {
    if (!submit.dataset.idleText) submit.dataset.idleText = submit.textContent;
    submit.textContent = busy ? busyText : submit.dataset.idleText;
  }
  form.querySelectorAll('input, button').forEach(control => {
    control.disabled = busy;
  });
}

async function loadPreviewPosts(username, limit, options = {}) {
  const requestSeq = options.requestSeq ?? apiRuntime.profileRequestSeq;
  const loader = document.getElementById('grid-loader');
  const endEl = document.getElementById('grid-end');
  try {
    apiRuntime.postsLoading = true;
    if (loader) loader.style.display = 'flex';
    if (endEl) endEl.style.display = 'none';
    const started = await apiRequest('/api/profile/index/start', {
      method: 'POST',
      body: { target: username, limit, force_refresh: Boolean(options.forceRefresh) },
    });
    const status = await pollProfileIndex(started.job_id, requestSeq);
    if (requestSeq !== apiRuntime.profileRequestSeq || state.currentProfile?.username !== username) return null;
    const result = status.result || {};
    const payload = {
      ok: true,
      source: 'fresh',
      profile: {
        ...(result.profile || {}),
        posts: result.posts || [],
      },
    };
    apiRuntime.postsLoading = false;
    state.currentProfile = mapApiProfile(payload);
    state.posts = mapApiPosts(result.posts);
    syncSelectionWithPosts();
    renderProfile(state.currentProfile);
    const freshness = document.querySelector('.freshness-text');
    if (freshness) freshness.textContent = 'Индекс публикаций обновлён';
    if (!options.initial) showToast(`Загружено ${state.posts.length} публикаций`, 'ok');
    return payload;
  } catch (error) {
    if (requestSeq !== apiRuntime.profileRequestSeq || state.currentProfile?.username !== username) return null;
    apiRuntime.postsLoading = false;
    renderPostsGrid();
    showToast(normalizeApiError(error), 'warn');
    return null;
  } finally {
    if (requestSeq === apiRuntime.profileRequestSeq && state.currentProfile?.username === username) {
      if (loader) loader.style.display = 'none';
      if (endEl) endEl.style.display = 'flex';
    }
  }
}

async function loadMorePosts() {
  if (!state.currentProfile || apiRuntime.postsLoading) return;
  const total = safeNumber(state.currentProfile.postsCount, state.posts.length);
  const nextLimit = Math.min(
    MAX_PREVIEW_POSTS,
    total || state.posts.length + LOAD_MORE_BATCH,
    state.posts.length + LOAD_MORE_BATCH,
  );
  await loadPreviewPosts(state.currentProfile.username, nextLimit, {
    requestSeq: apiRuntime.profileRequestSeq,
    forceRefresh: false,
    initial: false,
  });
}

function bindApiEventListeners() {
  if (window.__archiverApiBound) return;
  window.__archiverApiBound = true;
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('btn-clear-input');
  searchInput?.addEventListener('input', () => {
    if (clearBtn) clearBtn.style.display = searchInput.value ? 'flex' : 'none';
  });
  clearBtn?.addEventListener('click', () => {
    searchInput.value = '';
    clearBtn.style.display = 'none';
    searchInput.focus();
  });
  searchInput?.addEventListener('keydown', event => {
    if (event.key === 'Enter') loadProfile(searchInput.value);
  });
  document.getElementById('btn-search')?.addEventListener('click', () => loadProfile(searchInput?.value));
  document.querySelectorAll('.hint-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      if (searchInput) searchInput.value = chip.dataset.val;
      if (clearBtn) clearBtn.style.display = 'flex';
      loadProfile(chip.dataset.val);
    });
  });
  document.getElementById('btn-clear-history')?.addEventListener('click', () => {
    state.searchHistory = [];
    renderHistory();
    showToast('История поиска очищена', 'ok');
  });
  document.getElementById('btn-open-accounts')?.addEventListener('click', openAccountsDrawer);
  document.getElementById('btn-open-accounts-2')?.addEventListener('click', openAccountsDrawer);
  document.getElementById('btn-back')?.addEventListener('click', () => showPage('search'));
  document.getElementById('btn-refresh-profile')?.addEventListener('click', () => {
    if (state.currentProfile) loadProfile(state.currentProfile.username, { forceRefresh: true });
  });
  document.querySelectorAll('input[name="dl-mode"]').forEach(radio => {
    radio.addEventListener('change', () => setDownloadMode(radio.value));
  });
  const rangeSlider = document.getElementById('range-posts-count');
  rangeSlider?.addEventListener('input', () => {
    state.postsCount = parseInt(rangeSlider.value, 10);
    setText('range-val', state.postsCount);
    updateEstimate();
  });
  document.querySelectorAll('.toggle-switch').forEach(toggleSwitch => {
    toggleSwitch.addEventListener('click', () => {
      const isOn = toggleSwitch.dataset.state === 'on';
      toggleSwitch.dataset.state = isOn ? 'off' : 'on';
      if (toggleSwitch.id === 'toggle-full-json') state.options.fullJson = !isOn;
      if (toggleSwitch.id === 'toggle-images') state.options.images = !isOn;
      if (toggleSwitch.id === 'toggle-videos') state.options.videos = !isOn;
      if (toggleSwitch.id === 'toggle-comments') state.options.comments = !isOn;
      if (toggleSwitch.id === 'toggle-zip') state.options.zip = !isOn;
      updateEstimate();
    });
  });
  document.getElementById('btn-start-download')?.addEventListener('click', startDownload);
  document.getElementById('btn-pause')?.addEventListener('click', pauseDownload);
  document.getElementById('btn-stop')?.addEventListener('click', stopDownload);
  document.getElementById('btn-download-zip')?.addEventListener('click', event => {
    event.preventDefault();
    if (!apiRuntime.currentJobId) {
      showToast('ZIP доступен только после завершения задачи', 'warn');
      return;
    }
    window.location.href = `/api/jobs/${apiRuntime.currentJobId}/download`;
  });
  document.getElementById('btn-select-all')?.addEventListener('click', () => {
    const posts = getFilteredPosts();
    posts.forEach(post => state.selectedPosts.add(post.shortcode));
    renderPostsGrid();
    showToast(`Выбрано ${posts.length} публикаций`, 'ok');
  });
  document.getElementById('btn-deselect-all')?.addEventListener('click', () => {
    state.selectedPosts.clear();
    renderPostsGrid();
  });
  document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      state.activeFilter = chip.dataset.filter;
      renderPostsGrid();
    });
  });
  document.querySelectorAll('.posts-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      state.activeTab = tab.dataset.tab;
      if (state.activeTab === 'tagged') showToast('Отмеченные публикации недоступны через текущий API', 'warn');
      syncToolbarState();
      renderPostsGrid();
    });
  });
  document.getElementById('btn-load-more')?.addEventListener('click', loadMorePosts);
  document.getElementById('modal-close')?.addEventListener('click', closePostPreview);
  document.getElementById('post-preview-overlay')?.addEventListener('click', event => {
    if (event.target === document.getElementById('post-preview-overlay')) closePostPreview();
  });
  document.getElementById('modal-prev')?.addEventListener('click', () => navigatePreview(-1));
  document.getElementById('modal-next')?.addEventListener('click', () => navigatePreview(1));
  document.addEventListener('keydown', event => {
    if (!document.getElementById('post-preview-overlay')?.classList.contains('open')) return;
    if (event.key === 'Escape') closePostPreview();
    if (event.key === 'ArrowLeft') navigatePreview(-1);
    if (event.key === 'ArrowRight') navigatePreview(1);
  });
  document.getElementById('caption-toggle')?.addEventListener('click', () => {
    const caption = document.getElementById('preview-caption');
    const button = document.getElementById('caption-toggle');
    caption?.classList.toggle('expanded');
    if (button && caption) button.textContent = caption.classList.contains('expanded') ? 'Свернуть' : 'Читать полностью';
  });
  document.getElementById('preview-post-checkbox')?.addEventListener('change', event => {
    const post = getFilteredPosts()[state.previewPostIndex];
    if (!post) return;
    togglePostSelection(post.shortcode, null, event.target.checked);
    syncPostSelectionUi(post.shortcode, event.target.checked);
  });
  document.getElementById('btn-preview-download')?.addEventListener('click', () => {
    const post = getFilteredPosts()[state.previewPostIndex];
    if (!post) return;
    setDownloadMode('selected');
    if (['photo', 'carousel'].includes(post.type)) {
      state.options.images = true;
      const imagesToggle = document.getElementById('toggle-images');
      if (imagesToggle) imagesToggle.dataset.state = 'on';
    }
    if (['video', 'reel'].includes(post.type)) {
      state.options.videos = true;
      const videosToggle = document.getElementById('toggle-videos');
      if (videosToggle) videosToggle.dataset.state = 'on';
    }
    addPostToSelection(post, `Пост ${post.shortcode} добавлен в выборку`);
  });
  document.getElementById('btn-preview-meta')?.addEventListener('click', () => {
    const post = getFilteredPosts()[state.previewPostIndex];
    if (!post) return;
    setDownloadMode('selected');
    state.options.fullJson = true;
    state.options.images = false;
    state.options.videos = false;
    const jsonToggle = document.getElementById('toggle-full-json');
    const imagesToggle = document.getElementById('toggle-images');
    const videosToggle = document.getElementById('toggle-videos');
    if (jsonToggle) jsonToggle.dataset.state = 'on';
    if (imagesToggle) imagesToggle.dataset.state = 'off';
    if (videosToggle) videosToggle.dataset.state = 'off';
    addPostToSelection(post, `Пост ${post.shortcode} добавлен в выборку для JSON`);
  });
  document.getElementById('drawer-close')?.addEventListener('click', closeAccountsDrawer);
  document.getElementById('accounts-drawer-overlay')?.addEventListener('click', event => {
    if (event.target === document.getElementById('accounts-drawer-overlay')) closeAccountsDrawer();
  });
  document.getElementById('btn-add-account')?.addEventListener('click', () => {
    const form = document.getElementById('add-account-form');
    if (form) form.style.display = form.style.display === 'none' ? 'flex' : 'none';
  });
  document.getElementById('btn-cancel-add')?.addEventListener('click', resetAccountForm);
  document.getElementById('btn-confirm-add')?.addEventListener('click', uploadAccountSecret);
  const dropZone = document.getElementById('session-drop-zone');
  dropZone?.addEventListener('dragover', event => {
    event.preventDefault();
    dropZone.style.borderColor = 'var(--orange)';
    dropZone.style.background = 'var(--orange-glow)';
  });
  dropZone?.addEventListener('dragleave', () => {
    dropZone.style.borderColor = '';
    dropZone.style.background = '';
  });
  dropZone?.addEventListener('drop', event => {
    event.preventDefault();
    const file = event.dataTransfer.files[0];
    if (!file) return;
    apiRuntime.secretFile = file;
    const label = dropZone.querySelector('span');
    if (label) label.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    dropZone.style.color = 'var(--green)';
  });
  bindDropZoneFileInput();
  document.querySelectorAll('.platform-btn.platform-coming').forEach(button => {
    button.addEventListener('click', () => showToast(`${button.dataset.platform} — будет доступно в следующей версии`, 'warn'));
  });
  document.getElementById('setup-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    setText('setup-error', '');
    const password = document.getElementById('setup-password')?.value || '';
    const passwordConfirm = document.getElementById('setup-password-confirm')?.value || '';
    if (password !== passwordConfirm) {
      setText('setup-error', 'Пароли не совпадают');
      return;
    }
    try {
      setFormBusy(form, true, 'Инициализация...');
      await apiRequest('/api/auth/register', {
        method: 'POST',
        body: {
          username: document.getElementById('setup-admin')?.value.trim(),
          password,
        },
      });
      closeSetupOverlay();
      closeLoginOverlay();
      const badge = document.querySelector('.session-badge');
      if (badge) badge.textContent = document.getElementById('setup-admin')?.value.trim() || 'admin';
      await Promise.allSettled([loadAccountsFromApi(), loadSettingsIntoForm(), refreshJobsHistory()]);
      showToast('Администратор инициализирован', 'ok');
    } catch (error) {
      setText('setup-error', normalizeApiError(error));
    } finally {
      setFormBusy(form, false);
    }
  });
  document.getElementById('login-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    setText('login-error', '');
    try {
      setFormBusy(form, true, 'Входим...');
      await apiRequest('/api/auth/login', {
        method: 'POST',
        body: {
          username: document.getElementById('login-username')?.value.trim(),
          password: document.getElementById('login-password')?.value,
        },
      });
      closeLoginOverlay();
      const badge = document.querySelector('.session-badge');
      if (badge) badge.textContent = document.getElementById('login-username')?.value.trim() || 'admin';
      await Promise.allSettled([loadAccountsFromApi(), loadSettingsIntoForm(), refreshJobsHistory()]);
    } catch (error) {
      setText('login-error', normalizeApiError(error));
    } finally {
      setFormBusy(form, false);
    }
  });
  document.getElementById('btn-show-register')?.addEventListener('click', () => {
    closeLoginOverlay();
    openSetupOverlay();
  });
  document.getElementById('btn-show-login')?.addEventListener('click', () => {
    closeSetupOverlay();
    openLoginOverlay();
  });
  document.getElementById('btn-open-settings')?.addEventListener('click', async () => {
    document.getElementById('settings-overlay')?.classList.add('open');
    await loadSettingsIntoForm();
  });
  document.getElementById('settings-close')?.addEventListener('click', () => document.getElementById('settings-overlay')?.classList.remove('open'));
  document.getElementById('settings-overlay')?.addEventListener('click', event => {
    if (event.target === document.getElementById('settings-overlay')) document.getElementById('settings-overlay')?.classList.remove('open');
  });
  document.getElementById('settings-form')?.addEventListener('submit', saveSettings);
  document.getElementById('btn-logout')?.addEventListener('click', async () => {
    await apiRequest('/api/auth/logout', { method: 'POST' });
    const badge = document.querySelector('.session-badge');
    if (badge) badge.textContent = 'нужен вход';
    openLoginOverlay();
  });
}

function init() {
  showPage('search');
  renderHistory();
  bindApiEventListeners();
  setDownloadMode(state.downloadMode);
  updateEstimate();
  setTimeout(() => {
    const content = document.querySelector('.search-content');
    if (content) content.style.opacity = '1';
  }, 100);
  bootstrapAuthState();
}

document.addEventListener('DOMContentLoaded', init);
