/**
 * Instagram Archiver — Макет приложения
 * Все взаимодействия реализованы на чистом JS без бэкенда
 * Комментарии на русском языке
 */

'use strict';

/* =======================================================
   МОКОВЫЕ ДАННЫЕ
   Имитируют ответы будущего API
   ======================================================= */

/** Набор тестовых профилей для демонстрации */
const MOCK_PROFILES = {
  natgeo: {
    username: 'natgeo',
    fullname: 'National Geographic',
    initials: 'NG',
    bio: ['🌍 Inspiring people to care about the planet since 1888.', '📷 Photos & stories from our photographers & explorers.'],
    link: 'natgeo.com/wildwatch',
    posts: 1848,
    followers: '19.4M',
    following: 143,
    verified: true,
    type: 'Публичный',
    since: 'С 2010 года',
    category: 'Издание / СМИ',
  },
  nasa: {
    username: 'nasa',
    fullname: 'NASA',
    initials: 'NA',
    bio: ['🚀 Exploring the universe and our home planet.', '🔭 Follow us for the latest from space!'],
    link: 'nasa.gov',
    posts: 3241,
    followers: '95.2M',
    following: 57,
    verified: true,
    type: 'Публичный',
    since: 'С 2013 года',
    category: 'Государственная организация',
  },
  bbcearth: {
    username: 'bbcearth',
    fullname: 'BBC Earth',
    initials: 'BE',
    bio: ['🌊 Extraordinary stories about life on Earth.', '🦁 Wildlife. Nature. Adventure.'],
    link: 'bbc.com/earth',
    posts: 4420,
    followers: '11.7M',
    following: 32,
    verified: true,
    type: 'Публичный',
    since: 'С 2014 года',
    category: 'Медиа / Телевещание',
  },
};

/** Данные stories */
const MOCK_STORIES = [
  { label: 'Wildlife', short: 'WL' },
  { label: 'Explorers', short: 'EX' },
  { label: 'Ocean', short: 'OC' },
  { label: 'Travel', short: 'TR' },
  { label: 'Science', short: 'SC' },
  { label: 'Culture', short: 'CU' },
  { label: 'Climate', short: 'CL' },
  { label: 'Space', short: 'SP' },
  { label: 'Animals', short: 'AN' },
  { label: 'Adventure', short: 'AD' },
  { label: 'History', short: 'HI' },
  { label: 'Photo', short: 'PH' },
  { label: 'Video', short: 'VI' },
  { label: 'Special', short: 'SE' },
];

/** Типы постов и их иконки */
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
};

/** Генерация описаний постов (моковые данные) */
const CAPTIONS = [
  'A lone wolf traverses the snow-covered tundra of Yellowstone. These apex predators play a crucial role in maintaining the balance of ecosystems. 🐺❄️ #NatGeo #wildlife #wolves #Yellowstone',
  'The bioluminescent waters of Vaadhoo Island, Maldives glow in the dark — a result of millions of tiny phytoplankton emitting blue light when disturbed. 🌊✨ #ocean #bioluminescence #Maldives',
  'Rising 2,307 meters above sea level, Roraima is a tepui — a table-top mountain — straddling the borders of Venezuela, Guyana, and Brazil. Its isolated ecosystem has evolved unique species found nowhere else on Earth. #SouthAmerica #nature',
  'Portrait of a Tibetan fox in the vast grasslands of Qinghai province, China. Known for their distinctly square-shaped face, these stoic hunters are one of the most recognizable animals of the Tibetan Plateau. 🦊 #China #wildlife',
  'Storm clouds gather over the Namibian desert as the sun sets. The contrast between the arid landscape and the approaching rain creates a dramatic scene that photographers travel thousands of miles to capture. 📷 #Namibia #Africa',
];

/** Геолокации (моковые данные) */
const LOCATIONS = [
  'Yellowstone National Park, USA',
  'Vaadhoo Island, Maldives',
  'Mount Roraima, Venezuela',
  'Qinghai Province, China',
  'Namib Desert, Namibia',
  null, null, null, // Большинство постов без геолокации
];

/** Форматы изображений */
const FORMATS = ['JPEG', 'JPEG', 'JPEG', 'MP4', 'JPEG', 'JPEG', 'JPEG', 'MP4', 'JPEG'];

/** Разрешения (для метаданных) */
const RESOLUTIONS = ['1080×1080', '1080×1350', '1080×566', '1920×1080', '1080×1080', '1080×1920'];

/** Размеры файлов */
const FILE_SIZES = ['3.2 MB', '4.7 MB', '2.1 MB', '18.4 MB', '5.3 MB', '3.8 MB', '6.1 MB', '24.2 MB'];

/** Фоновые цвета-заглушки постов (имитируют разные фото) */
const POST_COLORS = [
  '#0D1B2A', '#1A0A1E', '#0A1628', '#1E0A0A', '#0A1E0A',
  '#1A1400', '#0A1A1A', '#160A28', '#1E0A14', '#0A1A0A',
  '#14100A', '#0A0A1E', '#1A0A0A', '#0A1410', '#140A1A',
  '#0E1C10', '#1C0E10', '#0E0E1C', '#1C1C0E', '#100E1C',
  '#0C1420', '#200C14', '#140C20', '#0C2014', '#200E0C',
  '#141414', '#0A0C10', '#10140C', '#0C0A14', '#14100C',
  '#080C14', '#140C08', '#0C1408', '#08140C', '#140808',
  '#0A0E12', '#120A0E', '#0E120A', '#0A120E', '#12100A',
  '#060A0E', '#0E060A', '#0A0E06', '#060E0A', '#0E0806',
  '#0A0608', '#08060A', '#060A08', '#080A06', '#0A0808',
];

/* =======================================================
   СОСТОЯНИЕ ПРИЛОЖЕНИЯ
   ======================================================= */
const state = {
  currentProfile: null,       // Текущий загруженный профиль
  currentPage: 'search',      // Текущая активная страница
  posts: [],                  // Массив загруженных постов
  selectedPosts: new Set(),   // Выбранные для скачивания посты
  previewPostIndex: -1,       // Индекс открытого в превью поста
  activeTab: 'posts',         // Активная вкладка (posts/reels/tagged)
  activeFilter: 'all',        // Активный фильтр типа контента
  downloadMode: 'last-n',     // Выбранный режим скачивания
  postsCount: 30,             // Количество постов для режима last-n
  options: {
    media: true,
    comments: false,
    stories: false,
    zip: true,
  },
  isDownloading: false,       // Идёт ли процесс скачивания
  downloadProgress: 0,        // Прогресс скачивания (0-100)
  downloadInterval: null,     // Таймер анимации прогресса
  searchHistory: ['natgeo', 'nasa'], // История поисков
};

/* =======================================================
   УТИЛИТЫ
   ======================================================= */

/**
 * Форматирует большое число в читаемый вид (1.2K, 5.4M)
 * @param {number} n
 * @returns {string}
 */
function formatNumber(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toString();
}

/**
 * Возвращает случайный элемент массива
 * @param {Array} arr
 */
function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

/**
 * Генерирует случайный shortcode, имитирующий Instagram
 * @returns {string}
 */
function randomShortcode() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-';
  return Array.from({ length: 11 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
}

/**
 * Возвращает случайную дату в диапазоне последних 3 лет
 * @returns {string}
 */
function randomDate() {
  const now = Date.now();
  const threeYearsAgo = now - 3 * 365 * 24 * 60 * 60 * 1000;
  const ts = threeYearsAgo + Math.random() * (now - threeYearsAgo);
  return new Date(ts).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * Разбирает введённый текст — URL или username
 * @param {string} input
 * @returns {string} чистый username
 */
function parseInput(input) {
  input = input.trim().toLowerCase();
  // Убираем @ в начале
  if (input.startsWith('@')) input = input.slice(1);
  // Извлекаем username из ссылки
  const match = input.match(/instagram\.com\/([^/?&\s]+)/);
  if (match) return match[1];
  return input;
}

/* =======================================================
   ГЕНЕРАЦИЯ ПОСТОВ
   ======================================================= */

/**
 * Генерирует массив моковых постов
 * @param {number} count - количество постов
 * @returns {Array}
 */
function generatePosts(count) {
  const types = ['photo', 'photo', 'photo', 'video', 'carousel', 'photo', 'photo', 'video', 'carousel'];
  return Array.from({ length: count }, (_, i) => {
    const type = types[i % types.length];
    const typeKeys = Object.keys(POST_TYPES);
    const postType = typeKeys[i % typeKeys.length];
    const shortcode = randomShortcode();
    const likes = Math.floor(Math.random() * 500000) + 10000;
    const comments = Math.floor(Math.random() * 5000) + 50;
    const format = postType === 'video' ? 'MP4' : 'JPEG';
    const resolution = pick(RESOLUTIONS);
    const fileSize = pick(FILE_SIZES);
    const location = pick(LOCATIONS);
    const date = randomDate();
    const caption = pick(CAPTIONS);
    const colorIdx = (i + Math.floor(Math.random() * 10)) % POST_COLORS.length;

    // Хэштеги извлекаем из описания
    const hashtags = caption.match(/#\w+/g) || [];

    return {
      id: i,
      type: postType,
      shortcode,
      likes,
      comments,
      format,
      resolution,
      fileSize,
      location,
      date,
      caption,
      hashtags,
      colorIdx,
      // Для каруселей — количество слайдов
      carouselCount: postType === 'carousel' ? Math.floor(Math.random() * 8) + 2 : 1,
    };
  });
}

/* =======================================================
   НАВИГАЦИЯ МЕЖДУ СТРАНИЦАМИ
   ======================================================= */

/**
 * Переключает активную страницу
 * @param {string} pageId - 'search' | 'profile'
 */
function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = document.getElementById(pageId === 'search' ? 'search-page' : 'profile-page');
  if (page) page.classList.add('active');
  state.currentPage = pageId;
}

/* =======================================================
   ПОИСК И ЗАГРУЗКА ПРОФИЛЯ
   ======================================================= */

/**
 * Показывает оверлей загрузки профиля с анимацией шагов
 * @param {string} username
 * @returns {Promise} завершается по окончании анимации
 */
function showLoader(username) {
  const overlay = document.getElementById('profile-loader');
  const primaryText = document.getElementById('loader-primary-text');
  const secondaryText = document.getElementById('loader-secondary-text');
  const steps = ['ls-1', 'ls-2', 'ls-3'];

  overlay.classList.add('visible');
  primaryText.textContent = `Загружаем @${username}...`;
  secondaryText.textContent = 'Подключение к Instagram API';

  // Сбрасываем все шаги
  steps.forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove('active', 'done');
  });

  return new Promise(resolve => {
    let step = 0;

    // Анимируем шаги загрузки последовательно
    const stepTexts = [
      ['Разрешение username', 'Запрос к Instaloader...'],
      ['Загрузка метаданных', 'Получение данных профиля...'],
      ['Превью публикаций', 'Загрузка последних постов...'],
    ];

    function nextStep() {
      if (step < steps.length) {
        // Помечаем предыдущий шаг как завершённый
        if (step > 0) document.getElementById(steps[step - 1]).classList.replace('active', 'done');
        const current = document.getElementById(steps[step]);
        current.classList.add('active');
        primaryText.textContent = stepTexts[step][0];
        secondaryText.textContent = stepTexts[step][1];
        step++;
        setTimeout(nextStep, 700 + Math.random() * 400);
      } else {
        // Все шаги завершены
        document.getElementById(steps[steps.length - 1]).classList.replace('active', 'done');
        setTimeout(() => {
          overlay.classList.remove('visible');
          resolve();
        }, 500);
      }
    }

    nextStep();
  });
}

/**
 * Основная функция загрузки профиля (мок)
 * @param {string} rawInput - то, что ввёл пользователь
 */
async function loadProfile(rawInput) {
  const username = parseInput(rawInput);

  if (!username) {
    showToast('Введите username или ссылку на профиль', 'warn');
    return;
  }

  // Проверяем есть ли профиль в моковых данных
  const profileData = MOCK_PROFILES[username] || {
    username,
    fullname: username.charAt(0).toUpperCase() + username.slice(1),
    initials: username.slice(0, 2).toUpperCase(),
    bio: ['Публичный профиль Instagram'],
    link: null,
    posts: Math.floor(Math.random() * 3000) + 100,
    followers: formatNumber(Math.floor(Math.random() * 5000000) + 1000),
    following: Math.floor(Math.random() * 500) + 10,
    verified: false,
    type: 'Публичный',
    since: `С ${2010 + Math.floor(Math.random() * 13)} года`,
    category: 'Личный блог',
  };

  // Добавляем в историю поиска
  addToHistory(username);

  // Показываем лоадер
  await showLoader(username);

  // Обновляем состояние
  state.currentProfile = profileData;
  state.posts = generatePosts(48);
  state.selectedPosts.clear();

  // Заполняем UI профиля
  renderProfile(profileData);

  // Переходим на страницу профиля
  showPage('profile');

  showToast(`Профиль @${username} успешно загружен`, 'ok');
}

/* =======================================================
   РЕНДЕРИНГ ПРОФИЛЯ
   ======================================================= */

/**
 * Заполняет левую панель данными профиля
 * @param {Object} profile
 */
function renderProfile(profile) {
  // Обновляем хлебные крошки
  document.getElementById('bc-username').textContent = profile.username;

  // Аватар: инициалы
  document.getElementById('profile-initials').textContent = profile.initials;
  // Верификация
  const verifiedBadge = document.querySelector('.verified-badge');
  verifiedBadge.style.display = profile.verified ? 'flex' : 'none';

  // Имя и username
  document.getElementById('profile-fullname').textContent = profile.fullname;
  document.getElementById('profile-username').textContent = `@${profile.username}`;

  // Счётчики
  document.getElementById('stat-posts').textContent = profile.posts.toLocaleString('ru');
  document.getElementById('stat-followers').textContent = profile.followers;
  document.getElementById('stat-following').textContent = profile.following.toLocaleString('ru');

  // Биография
  const bioEl = document.getElementById('profile-bio');
  bioEl.innerHTML = '';
  profile.bio.forEach(line => {
    const p = document.createElement('p');
    p.textContent = line;
    bioEl.appendChild(p);
  });
  if (profile.link) {
    const a = document.createElement('a');
    a.href = '#';
    a.className = 'bio-link';
    a.textContent = profile.link;
    a.onclick = e => e.preventDefault();
    bioEl.appendChild(a);
  }

  // Рендерим Stories
  renderStories();

  // Рендерим сетку постов
  renderPostsGrid();

  // Обновляем оценку параметров
  updateEstimate();
}

/* =======================================================
   STORIES
   ======================================================= */

/**
 * Генерирует и рендерит элементы Stories
 */
function renderStories() {
  const container = document.getElementById('stories-scroll');
  container.innerHTML = '';

  MOCK_STORIES.forEach((story, i) => {
    const item = document.createElement('div');
    item.className = 'story-item';
    item.innerHTML = `
      <div class="story-avatar color-${i % 7}">${story.short}</div>
      <span class="story-label">${story.label}</span>
    `;
    item.addEventListener('click', () => {
      showToast(`Story "${story.label}" — доступно для скачивания`, 'ok');
    });
    container.appendChild(item);
  });

  document.getElementById('stories-count').textContent = `${MOCK_STORIES.length} highlights`;
}

/* =======================================================
   СЕТКА ПОСТОВ
   ======================================================= */

/**
 * Возвращает посты, отфильтрованные по активному фильтру
 */
function getFilteredPosts() {
  if (state.activeFilter === 'all') return state.posts;
  return state.posts.filter(p => p.type === state.activeFilter);
}

/**
 * Рендерит карточки постов в сетке
 */
function renderPostsGrid() {
  const grid = document.getElementById('posts-grid');
  grid.innerHTML = '';

  const posts = getFilteredPosts();

  posts.forEach((post, index) => {
    const card = createPostCard(post, index);
    grid.appendChild(card);
  });

  // Обновляем счётчик выделенных
  updateSelectedCounter();

  // Показываем конец сетки
  setTimeout(() => {
    const gridEnd = document.getElementById('grid-end');
    gridEnd.style.display = 'flex';
    document.getElementById('total-loaded').textContent = posts.length;
  }, 100);
}

/**
 * Создаёт DOM-элемент карточки поста
 * @param {Object} post - данные поста
 * @param {number} index - индекс в массиве
 * @returns {HTMLElement}
 */
function createPostCard(post, index) {
  const card = document.createElement('div');
  card.className = `post-card${state.selectedPosts.has(post.id) ? ' selected' : ''}`;
  card.dataset.postId = post.id;
  card.dataset.postIndex = index;

  const typeInfo = POST_TYPES[post.type];
  const bgColor = POST_COLORS[post.colorIdx];

  card.innerHTML = `
    <!-- Цветная заглушка вместо реального изображения -->
    <div class="post-placeholder" style="background: ${bgColor};">
      <!-- Декоративные линии, имитирующие контент -->
      <div style="
        position: absolute; inset: 0;
        background: repeating-linear-gradient(
          45deg,
          transparent,
          transparent 10px,
          rgba(255,255,255,0.015) 10px,
          rgba(255,255,255,0.015) 11px
        );
      "></div>
    </div>

    <!-- Иконка типа медиа (угол) -->
    <div class="post-type-icon">
      ${typeInfo.icon}
    </div>

    <!-- Чекбокс выделения -->
    <div class="post-checkbox-wrap">
      <input
        type="checkbox"
        class="post-checkbox"
        ${state.selectedPosts.has(post.id) ? 'checked' : ''}
      />
    </div>

    <!-- Оверлей при наведении: лайки и комментарии -->
    <div class="post-overlay">
      <div class="post-overlay-stats">
        <div class="overlay-stat">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
          ${formatNumber(post.likes)}
        </div>
        <div class="overlay-stat">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          ${formatNumber(post.comments)}
        </div>
      </div>
    </div>
  `;

  // Обработчик клика на карточку — открываем превью
  card.addEventListener('click', (e) => {
    // Если кликнули на чекбокс — не открываем превью
    if (e.target.classList.contains('post-checkbox')) return;
    openPostPreview(index);
  });

  // Обработчик чекбокса выделения
  const checkbox = card.querySelector('.post-checkbox');
  checkbox.addEventListener('change', (e) => {
    e.stopPropagation();
    togglePostSelection(post.id, card, checkbox.checked);
  });

  return card;
}

/**
 * Переключает выделение поста
 * @param {number} postId
 * @param {HTMLElement} card
 * @param {boolean} selected
 */
function togglePostSelection(postId, card, selected) {
  if (selected) {
    state.selectedPosts.add(postId);
    card.classList.add('selected');
  } else {
    state.selectedPosts.delete(postId);
    card.classList.remove('selected');
  }
  updateSelectedCounter();
  updateEstimate();
}

/**
 * Обновляет счётчик выделенных постов в тулбаре
 */
function updateSelectedCounter() {
  document.getElementById('selected-count').textContent = state.selectedPosts.size;
}

/* =======================================================
   ПРЕВЬЮ ПОСТА (МОДАЛ)
   ======================================================= */

/**
 * Открывает модал предпросмотра для поста с индексом index
 * @param {number} index
 */
function openPostPreview(index) {
  const posts = getFilteredPosts();
  if (index < 0 || index >= posts.length) return;

  state.previewPostIndex = index;
  const post = posts[index];

  // Заполняем метаданные в правой панели модала
  const typeInfo = POST_TYPES[post.type];

  // Автор
  document.getElementById('preview-author-avatar').textContent = state.currentProfile?.initials || '??';
  document.getElementById('preview-author-name').textContent = state.currentProfile?.username || 'unknown';
  document.getElementById('preview-post-date').textContent = post.date;

  // Статистика
  document.getElementById('preview-likes').textContent = formatNumber(post.likes);
  document.getElementById('preview-comments-count').textContent = formatNumber(post.comments);
  document.getElementById('preview-type-label').textContent = typeInfo.label;
  document.getElementById('preview-post-id').textContent = `${post.shortcode}`;

  // Описание
  const captionEl = document.getElementById('preview-caption');
  captionEl.textContent = post.caption;
  captionEl.classList.remove('expanded');
  document.getElementById('caption-toggle').textContent = 'Читать полностью';

  // Хэштеги
  const hashEl = document.getElementById('preview-hashtags');
  hashEl.innerHTML = '';
  post.hashtags.forEach(tag => {
    const chip = document.createElement('span');
    chip.className = 'hashtag-chip';
    chip.textContent = tag;
    hashEl.appendChild(chip);
  });

  // Геолокация
  const locationEl = document.getElementById('preview-location');
  if (post.location) {
    locationEl.style.display = 'flex';
    document.getElementById('preview-location-text').textContent = post.location;
  } else {
    locationEl.style.display = 'none';
  }

  // Технические метаданные
  document.getElementById('pm-shortcode').textContent = post.shortcode;
  document.getElementById('pm-resolution').textContent = post.resolution;
  document.getElementById('pm-format').textContent = post.format;
  document.getElementById('pm-size').textContent = post.fileSize;
  document.getElementById('pm-timestamp').textContent = post.date;

  // Обновляем фон заглушки в медиа-области
  const placeholder = document.getElementById('preview-img-placeholder');
  placeholder.querySelector('.placeholder-pattern').style.background = POST_COLORS[post.colorIdx];

  // Точки карусели
  const dotsContainer = document.getElementById('carousel-dots');
  dotsContainer.innerHTML = '';
  if (post.type === 'carousel') {
    for (let i = 0; i < post.carouselCount; i++) {
      const dot = document.createElement('div');
      dot.className = `carousel-dot${i === 0 ? ' active' : ''}`;
      dotsContainer.appendChild(dot);
    }
  }

  // Синхронизируем чекбокс с состоянием выделения
  document.getElementById('preview-post-checkbox').checked = state.selectedPosts.has(post.id);

  // Открываем оверлей
  document.getElementById('post-preview-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

/**
 * Закрывает модал превью
 */
function closePostPreview() {
  document.getElementById('post-preview-overlay').classList.remove('open');
  document.body.style.overflow = '';
  state.previewPostIndex = -1;
}

/**
 * Навигация по постам внутри модала (вперёд/назад)
 * @param {number} direction - +1 | -1
 */
function navigatePreview(direction) {
  const posts = getFilteredPosts();
  const newIndex = state.previewPostIndex + direction;
  if (newIndex >= 0 && newIndex < posts.length) {
    openPostPreview(newIndex);
  }
}

/* =======================================================
   УПРАВЛЕНИЕ DRAWER АККАУНТОВ
   ======================================================= */

/** Открывает drawer аккаунтов */
function openAccountsDrawer() {
  document.getElementById('accounts-drawer-overlay').classList.add('open');
}

/** Закрывает drawer аккаунтов */
function closeAccountsDrawer() {
  document.getElementById('accounts-drawer-overlay').classList.remove('open');
}

/* =======================================================
   ИСТОРИЯ ПОИСКА
   ======================================================= */

/**
 * Добавляет username в историю поиска
 * @param {string} username
 */
function addToHistory(username) {
  // Удаляем дубликат если есть
  state.searchHistory = state.searchHistory.filter(h => h !== username);
  // Добавляем в начало
  state.searchHistory.unshift(username);
  // Ограничиваем до 5 записей
  state.searchHistory = state.searchHistory.slice(0, 5);
  renderHistory();
}

/**
 * Рендерит список последних поисков
 */
function renderHistory() {
  const list = document.getElementById('recent-list');
  list.innerHTML = '';
  const timeLabels = ['только что', '2 мин назад', '1 час назад', 'вчера', '2 дня назад'];
  state.searchHistory.forEach((username, i) => {
    const item = document.createElement('button');
    item.className = 'recent-item';
    item.innerHTML = `
      <span class="recent-icon">⏱</span>
      <span>${username}</span>
      <span class="recent-time">${timeLabels[i] || 'давно'}</span>
    `;
    item.addEventListener('click', () => {
      document.getElementById('search-input').value = username;
      loadProfile(username);
    });
    list.appendChild(item);
  });
}

/* =======================================================
   ОЦЕНКА ПАРАМЕТРОВ СКАЧИВАНИЯ
   ======================================================= */

/**
 * Обновляет блок оценки: количество постов, файлов, размер
 */
function updateEstimate() {
  let count = 0;

  if (state.downloadMode === 'last-n') {
    count = state.postsCount;
  } else if (state.downloadMode === 'selected') {
    count = state.selectedPosts.size || 0;
  } else if (state.downloadMode === 'meta-only') {
    count = 0;
  } else if (state.downloadMode === 'all-media') {
    count = state.currentProfile?.posts || 0;
  }

  const filesPerPost = state.options.media ? 2 : 0;
  const totalFiles = count * filesPerPost;
  const avgFileMb = state.options.media ? 6.5 : 0.02;
  const totalMb = (count * avgFileMb).toFixed(0);

  document.getElementById('est-posts').textContent = count > 0 ? count.toLocaleString('ru') : '—';
  document.getElementById('est-files').textContent = totalFiles > 0 ? `~${totalFiles}` : '—';
  document.getElementById('est-size').textContent = totalMb > 0 ? `~${totalMb} MB` : '< 1 MB';
}

/* =======================================================
   ПРОЦЕСС СКАЧИВАНИЯ (симуляция)
   ======================================================= */

/**
 * Запускает симуляцию процесса скачивания
 */
function startDownload() {
  if (state.isDownloading) return;

  state.isDownloading = true;
  state.downloadProgress = 0;

  const progressBlock = document.getElementById('progress-block');
  const startBtn = document.getElementById('btn-start-download');
  const downloadZipBtn = document.getElementById('btn-download-zip');

  // Показываем блок прогресса
  progressBlock.style.display = 'flex';
  startBtn.textContent = 'Задача запущена...';
  startBtn.style.opacity = '0.5';
  startBtn.style.pointerEvents = 'none';
  downloadZipBtn.style.display = 'none';

  let totalSteps;
  if (state.downloadMode === 'last-n') totalSteps = state.postsCount;
  else if (state.downloadMode === 'selected') totalSteps = state.selectedPosts.size || 10;
  else totalSteps = 50;

  document.getElementById('progress-total').textContent = totalSteps;

  const labels = [
    'Инициализация задачи...',
    'Загрузка метаданных профиля...',
    'Сканирование публикаций...',
    'Загрузка медиафайлов...',
    'Сохранение в базу данных...',
    'Упаковка в ZIP-архив...',
    'Завершение...',
  ];
  let labelIdx = 0;

  // Случайное появление rate-limit предупреждения
  const rateLimitAt = Math.random() > 0.5 ? Math.floor(totalSteps * 0.4) : -1;
  let rateLimitShown = false;

  state.downloadInterval = setInterval(() => {
    // Имитируем нестабильный прогресс (иногда медленный)
    const increment = Math.random() > 0.2 ? Math.floor(Math.random() * 3) + 1 : 0;
    state.downloadProgress = Math.min(100, state.downloadProgress + (increment / totalSteps) * 100);

    const current = Math.floor((state.downloadProgress / 100) * totalSteps);

    // Обновляем UI прогресса
    document.getElementById('progress-bar').style.width = `${state.downloadProgress.toFixed(1)}%`;
    document.getElementById('progress-pct').textContent = `${Math.floor(state.downloadProgress)}%`;
    document.getElementById('progress-current').textContent = current;
    document.getElementById('progress-label').textContent = labels[Math.min(labelIdx, labels.length - 1)];

    // Меняем текст метки по мере прогресса
    if (state.downloadProgress > 15 * labelIdx) labelIdx++;

    // Показываем rate limit предупреждение если нужно
    if (rateLimitAt > 0 && current >= rateLimitAt && !rateLimitShown) {
      rateLimitShown = true;
      document.getElementById('rate-limit-warn').style.display = 'flex';
      showToast('Rate limit Instagram — прогресс сохранён, задача на паузе', 'warn');
      // Имитируем паузу
      clearInterval(state.downloadInterval);
      setTimeout(() => {
        document.getElementById('rate-limit-warn').style.display = 'none';
        resumeDownload(totalSteps, labels);
      }, 4000);
    }

    // Завершение
    if (state.downloadProgress >= 100) {
      clearInterval(state.downloadInterval);
      finishDownload();
    }
  }, 120);
}

/**
 * Продолжает скачивание после паузы (rate limit)
 * @param {number} totalSteps
 * @param {string[]} labels
 */
function resumeDownload(totalSteps, labels) {
  let labelIdx = 4;
  state.downloadInterval = setInterval(() => {
    const increment = Math.floor(Math.random() * 2) + 1;
    state.downloadProgress = Math.min(100, state.downloadProgress + (increment / totalSteps) * 100);
    const current = Math.floor((state.downloadProgress / 100) * totalSteps);
    document.getElementById('progress-bar').style.width = `${state.downloadProgress.toFixed(1)}%`;
    document.getElementById('progress-pct').textContent = `${Math.floor(state.downloadProgress)}%`;
    document.getElementById('progress-current').textContent = current;
    document.getElementById('progress-label').textContent = labels[Math.min(labelIdx, labels.length - 1)];
    if (state.downloadProgress > 15 * labelIdx) labelIdx++;
    if (state.downloadProgress >= 100) {
      clearInterval(state.downloadInterval);
      finishDownload();
    }
  }, 150);
}

/**
 * Завершает скачивание: обновляет UI, показывает кнопку ZIP
 */
function finishDownload() {
  state.isDownloading = false;

  document.getElementById('progress-label').textContent = 'Архивирование завершено!';
  document.getElementById('progress-bar').style.background = 'var(--green)';

  // Показываем кнопку ZIP если включена опция
  if (state.options.zip) {
    const downloadZipBtn = document.getElementById('btn-download-zip');
    downloadZipBtn.style.display = 'flex';
  }

  // Восстанавливаем кнопку старта
  const startBtn = document.getElementById('btn-start-download');
  startBtn.textContent = 'Начать архивирование';
  startBtn.style.opacity = '1';
  startBtn.style.pointerEvents = 'auto';

  showToast('Архивирование завершено успешно! 🎉', 'ok');
}

/**
 * Ставит скачивание на паузу
 */
function pauseDownload() {
  if (!state.isDownloading) return;
  clearInterval(state.downloadInterval);
  document.getElementById('progress-label').textContent = 'Пауза — нажмите продолжить';
  document.getElementById('btn-pause').innerHTML = `
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <polygon points="5 3 19 12 5 21 5 3"/>
    </svg> Продолжить
  `;
  state.isDownloading = false;
  showToast('Задача приостановлена. Прогресс сохранён.', 'warn');
}

/**
 * Останавливает скачивание
 */
function stopDownload() {
  clearInterval(state.downloadInterval);
  state.isDownloading = false;
  state.downloadProgress = 0;

  document.getElementById('progress-block').style.display = 'none';
  document.getElementById('btn-start-download').textContent = 'Начать архивирование';
  document.getElementById('btn-start-download').style.opacity = '1';
  document.getElementById('btn-start-download').style.pointerEvents = 'auto';
  document.getElementById('progress-bar').style.background = 'var(--orange)';
  document.getElementById('btn-pause').innerHTML = `
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>
    </svg> Пауза
  `;

  showToast('Задача остановлена. Частичные данные сохранены.', 'warn');
}

/* =======================================================
   ТОСТЫ
   ======================================================= */

/**
 * Показывает всплывающее уведомление
 * @param {string} message - текст сообщения
 * @param {'ok'|'warn'|'err'} type - тип уведомления
 */
function showToast(message, type = 'ok') {
  const container = document.getElementById('toast-container');

  const icons = {
    ok: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2">
           <path d="M9 12l2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/>
         </svg>`,
    warn: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--orange)" stroke-width="2">
             <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
             <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
           </svg>`,
    err: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>`,
  };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `${icons[type] || ''}<span>${message}</span>`;

  container.appendChild(toast);

  // Удаляем через 3 секунды
  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/* =======================================================
   ИНИЦИАЛИЗАЦИЯ ВСЕХ СОБЫТИЙ
   ======================================================= */

/**
 * Инициализирует все обработчики событий при загрузке DOM
 */
function initEventListeners() {

  /* --- Поисковая страница --- */

  // Поле ввода: показываем/скрываем кнопку очистки
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('btn-clear-input');

  searchInput.addEventListener('input', () => {
    clearBtn.style.display = searchInput.value ? 'flex' : 'none';
  });

  // Кнопка очистки поля
  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    clearBtn.style.display = 'none';
    searchInput.focus();
  });

  // Нажатие Enter в поле поиска
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadProfile(searchInput.value);
  });

  // Кнопка "Загрузить профиль"
  document.getElementById('btn-search').addEventListener('click', () => {
    loadProfile(searchInput.value);
  });

  // Чипсы-примеры быстрого заполнения
  document.querySelectorAll('.hint-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      searchInput.value = chip.dataset.val;
      clearBtn.style.display = 'flex';
      loadProfile(chip.dataset.val);
    });
  });

  // Очистка истории поиска
  document.getElementById('btn-clear-history').addEventListener('click', () => {
    state.searchHistory = [];
    renderHistory();
    showToast('История поиска очищена', 'ok');
  });

  // Кнопка "Аккаунты" на поисковой странице
  document.getElementById('btn-open-accounts').addEventListener('click', openAccountsDrawer);

  /* --- Страница профиля --- */

  // Кнопка "Назад"
  document.getElementById('btn-back').addEventListener('click', () => {
    // Останавливаем скачивание если идёт
    if (state.isDownloading) stopDownload();
    showPage('search');
  });

  // Кнопка "Обновить профиль"
  document.getElementById('btn-refresh-profile').addEventListener('click', async () => {
    if (!state.currentProfile) return;
    showToast('Обновляем данные профиля...', 'ok');
    await showLoader(state.currentProfile.username);
    state.posts = generatePosts(48);
    renderPostsGrid();
    showToast('Данные обновлены', 'ok');
  });

  // Кнопка аккаунтов на странице профиля
  document.getElementById('btn-open-accounts-2').addEventListener('click', openAccountsDrawer);

  /* --- Режимы скачивания --- */

  // Радио-кнопки режима скачивания
  document.querySelectorAll('input[name="dl-mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
      state.downloadMode = radio.value;

      // Обновляем визуальные состояния карточек режимов
      document.querySelectorAll('.mode-card').forEach(card => card.classList.remove('active'));
      const label = radio.closest('.mode-option');
      if (label) label.querySelector('.mode-card').classList.add('active');

      // Показываем/скрываем параметр N
      const paramEl = document.getElementById('param-last-n');
      paramEl.style.display = state.downloadMode === 'last-n' ? 'block' : 'none';

      // Активируем чекбоксы в режиме "Выбранные"
      const checkboxes = document.querySelectorAll('.post-checkbox');
      checkboxes.forEach(cb => {
        cb.style.pointerEvents = state.downloadMode === 'selected' ? 'auto' : 'auto';
      });

      updateEstimate();
    });
  });

  // Слайдер количества постов
  const rangeSlider = document.getElementById('range-posts-count');
  rangeSlider.addEventListener('input', () => {
    state.postsCount = parseInt(rangeSlider.value);
    document.getElementById('range-val').textContent = state.postsCount;
    updateEstimate();
  });

  /* --- Глобальные опции (toggle switches) --- */

  document.querySelectorAll('.toggle-switch').forEach(toggleSwitch => {
    toggleSwitch.addEventListener('click', () => {
      const isOn = toggleSwitch.dataset.state === 'on';
      toggleSwitch.dataset.state = isOn ? 'off' : 'on';

      // Обновляем соответствующую опцию в состоянии
      const id = toggleSwitch.id;
      if (id === 'toggle-media') state.options.media = !isOn;
      if (id === 'toggle-comments') state.options.comments = !isOn;
      if (id === 'toggle-stories') state.options.stories = !isOn;
      if (id === 'toggle-zip') state.options.zip = !isOn;

      updateEstimate();
    });
  });

  /* --- Управление скачиванием --- */

  // Кнопка старта
  document.getElementById('btn-start-download').addEventListener('click', () => {
    if (!state.currentProfile) {
      showToast('Сначала загрузите профиль', 'warn');
      return;
    }
    if (state.downloadMode === 'selected' && state.selectedPosts.size === 0) {
      showToast('Выберите хотя бы один пост для скачивания', 'warn');
      return;
    }
    startDownload();
  });

  // Кнопка паузы
  document.getElementById('btn-pause').addEventListener('click', pauseDownload);

  // Кнопка остановки
  document.getElementById('btn-stop').addEventListener('click', stopDownload);

  // Кнопка скачивания ZIP
  document.getElementById('btn-download-zip').addEventListener('click', () => {
    showToast('Скачивание ZIP начато (мок)', 'ok');
  });

  /* --- Панель инструментов постов --- */

  // Вкладки Posts / Reels / Tagged
  document.querySelectorAll('.posts-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.posts-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      state.activeTab = tab.dataset.tab;

      // В режиме Reels/Tagged показываем другой набор постов (мок)
      if (state.currentProfile) {
        state.posts = generatePosts(tab.dataset.tab === 'posts' ? 48 : Math.floor(Math.random() * 20) + 5);
        renderPostsGrid();
      }
    });
  });

  // Кнопка "Выбрать все"
  document.getElementById('btn-select-all').addEventListener('click', () => {
    const posts = getFilteredPosts();
    posts.forEach(post => state.selectedPosts.add(post.id));

    // Синхронизируем чекбоксы
    document.querySelectorAll('.post-card').forEach(card => {
      card.classList.add('selected');
      const cb = card.querySelector('.post-checkbox');
      if (cb) cb.checked = true;
    });

    updateSelectedCounter();
    updateEstimate();
    showToast(`Выбрано ${posts.length} постов`, 'ok');
  });

  // Кнопка "Снять выбор"
  document.getElementById('btn-deselect-all').addEventListener('click', () => {
    state.selectedPosts.clear();

    document.querySelectorAll('.post-card').forEach(card => {
      card.classList.remove('selected');
      const cb = card.querySelector('.post-checkbox');
      if (cb) cb.checked = false;
    });

    updateSelectedCounter();
    updateEstimate();
  });

  // Фильтр-чипсы по типу контента
  document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.activeFilter = chip.dataset.filter;
      if (state.currentProfile) renderPostsGrid();
    });
  });

  // Кнопка "Загрузить ещё"
  document.getElementById('btn-load-more').addEventListener('click', async () => {
    const loader = document.getElementById('grid-loader');
    const endEl = document.getElementById('grid-end');

    loader.style.display = 'flex';
    endEl.style.display = 'none';

    // Имитируем задержку загрузки
    await new Promise(r => setTimeout(r, 1200 + Math.random() * 800));

    // Добавляем новые посты
    const newPosts = generatePosts(24);
    const startIdx = state.posts.length;
    newPosts.forEach((p, i) => {
      p.id = startIdx + i;
    });
    state.posts = [...state.posts, ...newPosts];

    // Рендерим новые карточки
    const grid = document.getElementById('posts-grid');
    const filtered = getFilteredPosts();
    filtered.slice(startIdx).forEach((post, index) => {
      grid.appendChild(createPostCard(post, startIdx + index));
    });

    loader.style.display = 'none';
    endEl.style.display = 'flex';
    document.getElementById('total-loaded').textContent = filtered.length;

    showToast(`Загружено ещё ${newPosts.length} постов`, 'ok');
  });

  /* --- Модал предпросмотра поста --- */

  // Закрытие по кнопке
  document.getElementById('modal-close').addEventListener('click', closePostPreview);

  // Закрытие по клику на фон оверлея
  document.getElementById('post-preview-overlay').addEventListener('click', (e) => {
    if (e.target === document.getElementById('post-preview-overlay')) closePostPreview();
  });

  // Навигация: предыдущий пост
  document.getElementById('modal-prev').addEventListener('click', () => navigatePreview(-1));

  // Навигация: следующий пост
  document.getElementById('modal-next').addEventListener('click', () => navigatePreview(+1));

  // Клавиатурная навигация в модале
  document.addEventListener('keydown', (e) => {
    if (!document.getElementById('post-preview-overlay').classList.contains('open')) return;
    if (e.key === 'Escape') closePostPreview();
    if (e.key === 'ArrowLeft') navigatePreview(-1);
    if (e.key === 'ArrowRight') navigatePreview(+1);
  });

  // Разворот описания
  document.getElementById('caption-toggle').addEventListener('click', () => {
    const caption = document.getElementById('preview-caption');
    const btn = document.getElementById('caption-toggle');
    caption.classList.toggle('expanded');
    btn.textContent = caption.classList.contains('expanded') ? 'Свернуть' : 'Читать полностью';
  });

  // Чекбокс выделения поста в модале
  document.getElementById('preview-post-checkbox').addEventListener('change', (e) => {
    const posts = getFilteredPosts();
    const post = posts[state.previewPostIndex];
    if (!post) return;

    if (e.target.checked) {
      state.selectedPosts.add(post.id);
    } else {
      state.selectedPosts.delete(post.id);
    }

    // Синхронизируем с сеткой
    const gridCard = document.querySelector(`.post-card[data-post-id="${post.id}"]`);
    if (gridCard) {
      gridCard.classList.toggle('selected', e.target.checked);
      const cb = gridCard.querySelector('.post-checkbox');
      if (cb) cb.checked = e.target.checked;
    }

    updateSelectedCounter();
    updateEstimate();
  });

  // Кнопка "Скачать этот пост" в модале
  document.getElementById('btn-preview-download').addEventListener('click', () => {
    const posts = getFilteredPosts();
    const post = posts[state.previewPostIndex];
    if (post) showToast(`Пост ${post.shortcode} добавлен в очередь загрузки`, 'ok');
  });

  // Кнопка "Только JSON" в модале
  document.getElementById('btn-preview-meta').addEventListener('click', () => {
    const posts = getFilteredPosts();
    const post = posts[state.previewPostIndex];
    if (post) showToast(`Метаданные JSON для ${post.shortcode} сохранены`, 'ok');
  });

  /* --- Drawer аккаунтов --- */

  // Закрытие drawer
  document.getElementById('drawer-close').addEventListener('click', closeAccountsDrawer);
  document.getElementById('accounts-drawer-overlay').addEventListener('click', (e) => {
    if (e.target === document.getElementById('accounts-drawer-overlay')) closeAccountsDrawer();
  });

  // Кнопка добавления аккаунта
  document.getElementById('btn-add-account').addEventListener('click', () => {
    const form = document.getElementById('add-account-form');
    form.style.display = form.style.display === 'none' ? 'flex' : 'none';
  });

  // Отмена добавления аккаунта
  document.getElementById('btn-cancel-add').addEventListener('click', () => {
    document.getElementById('add-account-form').style.display = 'none';
    document.getElementById('new-account-username').value = '';
  });

  // Подтверждение добавления аккаунта
  document.getElementById('btn-confirm-add').addEventListener('click', () => {
    const username = document.getElementById('new-account-username').value.trim();
    if (!username) {
      showToast('Введите username аккаунта', 'warn');
      return;
    }
    document.getElementById('add-account-form').style.display = 'none';
    document.getElementById('new-account-username').value = '';
    showToast(`Аккаунт @${username} добавлен (мок)`, 'ok');
    // Обновляем счётчик бейджа
    document.querySelectorAll('.accounts-badge').forEach(b => {
      b.textContent = parseInt(b.textContent) + 1;
    });
  });

  // Зона перетаскивания session файла
  const dropZone = document.getElementById('session-drop-zone');
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = 'var(--orange)';
    dropZone.style.background = 'var(--orange-glow)';
  });
  dropZone.addEventListener('dragleave', () => {
    dropZone.style.borderColor = '';
    dropZone.style.background = '';
  });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = '';
    dropZone.style.background = '';
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      dropZone.innerHTML = `<span>✔ ${files[0].name} (${(files[0].size / 1024).toFixed(1)} KB)</span>`;
      dropZone.style.color = 'var(--green)';
    }
  });

  /* --- Платформенные кнопки --- */

  // Кнопки будущих платформ
  document.querySelectorAll('.platform-btn.platform-coming').forEach(btn => {
    btn.addEventListener('click', () => {
      showToast(`${btn.dataset.platform} — будет доступно в следующей версии`, 'warn');
    });
  });

  /* --- Stories clicks --- */

  document.getElementById('stories-scroll').addEventListener('click', (e) => {
    const item = e.target.closest('.story-item');
    if (item) {
      const label = item.querySelector('.story-label')?.textContent;
      showToast(`Открываем highlight: ${label}`, 'ok');
    }
  });
}

/* =======================================================
   ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
   ======================================================= */

/**
 * Точка входа — запускается после загрузки DOM
 */
function init() {
  // Показываем поисковую страницу
  showPage('search');

  // Инициализируем историю поиска
  renderHistory();

  // Подключаем все обработчики событий
  initEventListeners();

  // Небольшая задержка для анимации входа
  setTimeout(() => {
    document.querySelector('.search-content').style.opacity = '1';
  }, 100);

  // Демо: предзаполняем поле поиска первым элементом истории
  if (state.searchHistory.length > 0) {
    document.getElementById('search-input').value = '';
  }

  console.log('[Archiver] Приложение инициализировано. Версия v0.9.1');
  console.log('[Archiver] Это макет без бэкенда. Все данные являются демонстрационными.');
}

// Запускаем после загрузки DOM
document.addEventListener('DOMContentLoaded', init);
