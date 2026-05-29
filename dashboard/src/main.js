import './style.css';
import logoUrl from './assets/logo.png';

// Credentials Configuration
const VALID_USERNAME = 'admin';
const VALID_PASSWORD = 'aisteel2026';

// Google Sheets CSV Export URL
const SPREADSHEET_CSV_URL = 'https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/gviz/tq?tqx=out:csv&sheet=AllData';

// State Management
let state = {
    isAuthenticated: localStorage.getItem('aisteel_auth') === 'true',
    user: localStorage.getItem('aisteel_user') || '',
    loading: false,
    records: [],
    searchQuery: '',
    filterSource: 'all', // 'all', 'text', 'voice'
    loginError: '',
    activeAudio: null, // Currently playing audio element
    activeAudioId: null, // ID of currently playing record
    audioProgress: 0
};

// Application Mounting & Router
function initApp() {
    render();
    if (state.isAuthenticated) {
        fetchSheetData();
    }
}

// Custom CSV Parser supporting quotes and line breaks
function parseCSV(csvText) {
    const lines = [];
    let currentLine = [];
    let insideQuote = false;
    let currentValue = '';
    
    for (let i = 0; i < csvText.length; i++) {
        const char = csvText[i];
        const nextChar = csvText[i+1];
        
        if (char === '"') {
            if (insideQuote && nextChar === '"') {
                currentValue += '"';
                i++; // Skip next quote
            } else {
                insideQuote = !insideQuote;
            }
        } else if (char === ',' && !insideQuote) {
            currentLine.push(currentValue);
            currentValue = '';
        } else if ((char === '\n' || char === '\r') && !insideQuote) {
            if (char === '\r' && nextChar === '\n') {
                i++; // Skip \n
            }
            currentLine.push(currentValue);
            lines.push(currentLine);
            currentLine = [];
            currentValue = '';
        } else {
            currentValue += char;
        }
    }
    if (currentValue || currentLine.length > 0) {
        currentLine.push(currentValue);
        lines.push(currentLine);
    }
    return lines;
}

// Fetch Google Sheet Data
async function fetchSheetData() {
    state.loading = true;
    render();
    
    try {
        const response = await fetch(SPREADSHEET_CSV_URL);
        if (!response.ok) throw new Error('خطا در بارگیری داده‌ها از گوگل شیت');
        
        const csvText = await response.text();
        const parsedLines = parseCSV(csvText);
        
        if (parsedLines.length < 2) {
            state.records = [];
            state.loading = false;
            render();
            return;
        }
        
        const headers = parsedLines[0].map(h => h.trim());
        const rawRows = parsedLines.slice(1);
        
        state.records = rawRows.map(row => {
            const item = {};
            headers.forEach((h, idx) => {
                item[h] = row[idx] || '';
            });
            return item;
        }).filter(item => item.ID || item.Date); // Filter empty rows
        
        // Reverse chronological order (latest messages at top)
        state.records.reverse();
        
    } catch (error) {
        console.error('Error fetching sheet data:', error);
        alert('بارگیری ناموفق: لطفاً دسترسی اینترنت خود را بررسی کنید.');
    } finally {
        state.loading = false;
        render();
    }
}

// Terminology Highlighter
function highlightKeywords(text) {
    if (!text) return '';
    const keywords = [
        /AiSteel/gi,
        /تیرآهن/g,
        /تیر آهن/g,
        /میلگرد/g,
        /میل گرد/g,
        /آهن‌آلات/g,
        /آهن آلات/g,
        /نبشی/g,
        /پروفیل/g,
        /لوله/g,
        /ریخته‌گری/g,
        /ریخته گری/g,
        /خرید فولاد/g
    ];
    
    let highlighted = text;
    keywords.forEach(keyword => {
        highlighted = highlighted.replace(keyword, (match) => {
            return `<span class="highlight-tag">${match}</span>`;
        });
    });
    
    return highlighted;
}

// Authenticate user login
function handleLogin(username, password) {
    if (username.trim().toLowerCase() === VALID_USERNAME && password === VALID_PASSWORD) {
        state.isAuthenticated = true;
        state.user = username;
        state.loginError = '';
        localStorage.setItem('aisteel_auth', 'true');
        localStorage.setItem('aisteel_user', username);
        fetchSheetData();
    } else {
        state.loginError = 'نام کاربری یا رمز عبور اشتباه است!';
        render();
    }
}

// Log out user
function handleLogout() {
    state.isAuthenticated = false;
    state.records = [];
    localStorage.removeItem('aisteel_auth');
    localStorage.removeItem('aisteel_user');
    if (state.activeAudio) {
        state.activeAudio.pause();
        state.activeAudio = null;
        state.activeAudioId = null;
    }
    render();
}

// Custom HTML5 Audio Player Controller
function toggleAudio(recordId, audioFileName) {
    // If clicking same active audio, toggle play/pause
    if (state.activeAudioId === recordId && state.activeAudio) {
        if (state.activeAudio.paused) {
            state.activeAudio.play();
        } else {
            state.activeAudio.pause();
        }
        render();
        return;
    }
    
    // Stop currently playing audio
    if (state.activeAudio) {
        state.activeAudio.pause();
    }
    
    // In our python script, extracted files are placed temporarily in temp_audio.
    // To allow web playing, we point to `/temp_audio/` served relative to workspace root
    const audioUrl = `/temp_audio/${audioFileName}`;
    
    const audio = new Audio(audioUrl);
    state.activeAudio = audio;
    state.activeAudioId = recordId;
    state.audioProgress = 0;
    
    audio.play().catch(err => {
        console.warn('Audio play failed: local file is inside zip or needs local server', err);
        alert(`فایل صوتی ${audioFileName} به صورت محلی در سرور قرار نگرفته است. برای شنیدن ویس، پروژه را با مفسر لوکال اجرا کنید.`);
        state.activeAudio = null;
        state.activeAudioId = null;
        render();
    });
    
    audio.addEventListener('timeupdate', () => {
        if (audio.duration) {
            state.audioProgress = (audio.currentTime / audio.duration) * 100;
            const progressEl = document.querySelector(`.progress-${recordId}`);
            if (progressEl) {
                progressEl.style.width = `${state.audioProgress}%`;
            }
        }
    });
    
    audio.addEventListener('ended', () => {
        state.activeAudio = null;
        state.activeAudioId = null;
        state.audioProgress = 0;
        render();
    });
    
    render();
}

// HTML Component Generators
function getLoginHTML() {
    return `
        <div class="login-container">
            <div class="login-card glass-panel">
                <div class="login-logo-container">
                    <img src="${logoUrl}" alt="AiSteel Logo" class="login-logo">
                </div>
                <div class="login-header">
                    <h2>خوش آمدید</h2>
                    <p>داشبورد یکپارچه نظارت و آنالیز داده‌های AiSteel</p>
                </div>
                
                ${state.loginError ? `
                    <div class="error-message">
                        <i class="fas fa-exclamation-triangle"></i>
                        <span>${state.loginError}</span>
                    </div>
                ` : ''}
                
                <form id="loginForm">
                    <div class="form-group">
                        <label class="form-label" for="username">نام کاربری</label>
                        <div class="input-wrapper">
                            <input class="form-input" type="text" id="username" placeholder="نام کاربری خود را وارد کنید" required autocomplete="username">
                            <i class="fas fa-user input-icon"></i>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="password">رمز عبور</label>
                        <div class="input-wrapper">
                            <input class="form-input" type="password" id="password" placeholder="••••••••" required autocomplete="current-password">
                            <i class="fas fa-lock input-icon"></i>
                        </div>
                    </div>
                    <button class="btn-primary" type="submit">
                        <span>ورود به پنل مدیریت</span>
                        <i class="fas fa-arrow-left"></i>
                    </button>
                </form>
            </div>
        </div>
    `;
}

function getDashboardHTML() {
    // 1. Calculate statistics
    const totalRecords = state.records.length;
    const voiceRecords = state.records.filter(r => r.Source === 'Voice');
    const successTranscripts = voiceRecords.filter(r => r['Transcription Status'] === 'Success').length;
    
    let totalDuration = 0;
    voiceRecords.forEach(r => {
        const d = parseFloat(r.Duration);
        if (!isNaN(d)) totalDuration += d;
    });
    
    // 2. Filter records based on active controls
    const filteredRecords = state.records.filter(r => {
        // Source Filter
        if (state.filterSource === 'text' && r.Source !== 'Text') return false;
        if (state.filterSource === 'voice' && r.Source !== 'Voice') return false;
        
        // Search Query Filter
        if (state.searchQuery) {
            const query = state.searchQuery.toLowerCase();
            const content = (r['Raw Content'] || '').toLowerCase();
            const sender = (r['Created By'] || '').toLowerCase();
            const transcript = (r['Transcript'] || '').toLowerCase();
            
            return content.includes(query) || sender.includes(query) || transcript.includes(query);
        }
        
        return true;
    });

    return `
        <div class="dashboard-container">
            <!-- Navigation Header -->
            <nav class="navbar glass-panel">
                <div class="navbar-actions">
                    <button class="btn-icon" id="logoutBtn" title="خروج از حساب">
                        <i class="fas fa-sign-out-alt"></i>
                    </button>
                    <span class="sender-name">کاربر: ${state.user}</span>
                </div>
                <div class="navbar-brand">
                    <span class="text-gradient-steel" style="font-family: var(--font-outfit); font-weight: 800; font-size: 20px;">AiSteel Dashboard</span>
                    <img src="${logoUrl}" alt="AiSteel Logo" class="navbar-logo">
                </div>
            </nav>

            <main class="main-content">
                <!-- Statistics Cards -->
                <section class="stats-grid">
                    <div class="stat-card glass-panel">
                        <div class="stat-icon total"><i class="fas fa-envelope"></i></div>
                        <div class="stat-info">
                            <h3>کل پیام‌های چت</h3>
                            <div class="stat-number">${totalRecords}</div>
                        </div>
                    </div>
                    <div class="stat-card glass-panel">
                        <div class="stat-icon audio"><i class="fas fa-microphone"></i></div>
                        <div class="stat-info">
                            <h3>فایل‌های صوتی</h3>
                            <div class="stat-number">${voiceRecords.length}</div>
                        </div>
                    </div>
                    <div class="stat-card glass-panel">
                        <div class="stat-icon success"><i class="fas fa-check-circle"></i></div>
                        <div class="stat-info">
                            <h3>متنی‌سازی موفق</h3>
                            <div class="stat-number">${voiceRecords.length > 0 ? Math.round((successTranscripts / voiceRecords.length) * 100) : 0}%</div>
                        </div>
                    </div>
                    <div class="stat-card glass-panel">
                        <div class="stat-icon duration"><i class="fas fa-clock"></i></div>
                        <div class="stat-info">
                            <h3>کل زمان مکالمات</h3>
                            <div class="stat-number">${Math.round(totalDuration)} ثانیه</div>
                        </div>
                    </div>
                </section>

                <!-- Search & Filters Control Bar -->
                <section class="control-bar glass-panel">
                    <div class="filter-actions">
                        <button class="filter-btn ${state.filterSource === 'all' ? 'active' : ''}" id="filterAll">
                            <span>همه پیام‌ها</span>
                        </button>
                        <button class="filter-btn ${state.filterSource === 'text' ? 'active' : ''}" id="filterText">
                            <i class="fas fa-align-right"></i>
                            <span>متن خام</span>
                        </button>
                        <button class="filter-btn ${state.filterSource === 'voice' ? 'active' : ''}" id="filterVoice">
                            <i class="fas fa-microphone"></i>
                            <span>صداها</span>
                        </button>
                    </div>
                    <div class="search-box">
                        <input class="search-input" type="text" id="searchInput" placeholder="جستجو در پیام‌ها، ترنسکریپت‌ها یا فرستنده‌ها..." value="${state.searchQuery}">
                        <i class="fas fa-search search-icon"></i>
                    </div>
                </section>

                <!-- Loading State / Record Grid -->
                ${state.loading ? `
                    <div class="loading-box glass-panel">
                        <div class="spinner"></div>
                        <p>درحال واکشی و آنالیز اطلاعات گوگل شیت...</p>
                    </div>
                ` : `
                    <section class="grid-container">
                        ${filteredRecords.length === 0 ? `
                            <div class="loading-box glass-panel">
                                <i class="fas fa-folder-open" style="font-size: 40px; color: #8b949e; margin-bottom: 12px;"></i>
                                <p>هیچ پیامی با فیلترها و جستجوی شما مطابقت ندارد.</p>
                            </div>
                        ` : filteredRecords.map(r => getRecordCardHTML(r)).join('')}
                    </section>
                `}
            </main>
        </div>
    `;
}

function getRecordCardHTML(r) {
    const isVoice = r.Source === 'Voice';
    const cleanContent = highlightKeywords(r['Raw Content']);
    const rawTranscript = highlightKeywords(r['Transcript']);
    
    // Get sender initials for avatar
    const sender = r['Created By'] || 'کاربر';
    const initials = sender.substring(0, 1).toUpperCase();
    
    const isPlaying = state.activeAudioId === r.ID && state.activeAudio && !state.activeAudio.paused;

    return `
        <article class="record-card glass-panel">
            <div class="card-header">
                <div class="meta-info">
                    <span class="source-badge ${isVoice ? 'voice' : 'text'}">${isVoice ? 'پیام صوتی' : 'پیام متنی'}</span>
                    <span><i class="far fa-calendar-alt"></i> ${r.Date}</span>
                    <span><i class="far fa-clock"></i> ${r.Time}</span>
                </div>
                <div class="sender-badge">
                    <span class="sender-name">${sender}</span>
                    <span class="sender-avatar">${initials}</span>
                </div>
            </div>
            
            <div class="card-body">
                ${cleanContent}
            </div>
            
            ${isVoice && r['Audio File'] ? `
                <!-- Audio Waveform Box -->
                <div class="audio-player-box">
                    <span class="audio-duration">${r.Duration} ثانیه</span>
                    <div class="audio-track-info">
                        <span class="audio-file-name">${r['Audio File']}</span>
                        <div class="audio-waveform-fallback">
                            <div class="audio-waveform-progress progress-${r.ID}" style="width: ${state.activeAudioId === r.ID ? state.audioProgress : 0}%"></div>
                        </div>
                    </div>
                    <button class="play-btn" onclick="window.toggleAudio('${r.ID}', '${r['Audio File']}')">
                        <i class="fas ${isPlaying ? 'fa-pause' : 'fa-play'}"></i>
                    </button>
                </div>
                
                ${r['Transcription Status'] === 'Success' && rawTranscript ? `
                    <div class="card-body" style="margin-top: 12px; font-size: 13px; color: #8b949e; border-top: 1px dashed var(--border-metal); padding-top: 10px;">
                        <strong><i class="fas fa-quote-right" style="font-size: 10px; margin-left: 4px;"></i> متن ترنسکریپت خام:</strong><br>
                        ${rawTranscript}
                    </div>
                ` : ''}
            ${r['Transcription Status'] !== 'Success' && r['Transcription Status'] !== 'N/A' ? `
                <div class="error-message" style="margin-top: 12px; margin-bottom: 0; padding: 6px 12px; font-size: 12px;">
                    <i class="fas fa-exclamation-triangle"></i>
                    <span>متنی‌سازی ناموفق: ${r['Transcription Status']}</span>
                </div>
            ` : ''}
            ` : ''}
        </article>
    `;
}

// Unified Render Engine
function render() {
    const appEl = document.getElementById('app');
    if (!appEl) return;
    
    if (!state.isAuthenticated) {
        appEl.innerHTML = getLoginHTML();
        
        // Bind Login Actions
        const loginForm = document.getElementById('loginForm');
        if (loginForm) {
            loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                handleLogin(username, password);
            });
        }
    } else {
        appEl.innerHTML = getDashboardHTML();
        
        // Bind Logout Actions
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', handleLogout);
        }
        
        // Bind Search Event
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                state.searchQuery = e.target.value;
                render();
                // Maintain focus at the end of input
                const inp = document.getElementById('searchInput');
                if (inp) {
                    inp.focus();
                    inp.setSelectionRange(inp.value.length, inp.value.length);
                }
            });
        }
        
        // Bind Source Filters
        const filterAll = document.getElementById('filterAll');
        const filterText = document.getElementById('filterText');
        const filterVoice = document.getElementById('filterVoice');
        
        if (filterAll) {
            filterAll.addEventListener('click', () => {
                state.filterSource = 'all';
                render();
            });
        }
        if (filterText) {
            filterText.addEventListener('click', () => {
                state.filterSource = 'text';
                render();
            });
        }
        if (filterVoice) {
            filterVoice.addEventListener('click', () => {
                state.filterSource = 'voice';
                render();
            });
        }
    }
}

// Global Audio Binding to allow onclick in generated HTML
window.toggleAudio = toggleAudio;

// Initialize
document.addEventListener('DOMContentLoaded', initApp);
initApp();
