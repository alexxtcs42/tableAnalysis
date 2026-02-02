class CafeTableAnalyzer {
    constructor() {
        this.models = {};
        this.history = JSON.parse(localStorage.getItem('cafeAnalysisHistory') || '[]');
        this.currentResults = null;
        this.initElements();
        this.initEventListeners();
        this.loadHistory();
        this.apiBaseUrl = 'http://localhost:5000';
    }

    initElements() {
        this.fileInput = document.getElementById('fileInput');
        this.videoElement = document.getElementById('videoElement');
        this.imageCanvas = document.getElementById('imageCanvas');
        this.resultCanvas = document.getElementById('resultCanvas');
        this.processBtn = document.getElementById('processBtn');
        this.resultsContainer = document.getElementById('resultsContainer');
        this.historyList = document.getElementById('historyList');
        this.totalTablesElement = document.getElementById('totalTables');
        this.occupiedTablesElement = document.getElementById('occupiedTables');
        this.freeTablesElement = document.getElementById('freeTables');
        this.peopleCountElement = document.getElementById('peopleCount');
        this.occupancyBar = document.getElementById('occupancyBar');
        this.occupancyPercent = document.getElementById('occupancyPercent');
    }

    initEventListeners() {
        this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        this.processBtn.addEventListener('click', () => this.processMedia());
        document.getElementById('cameraBtn').addEventListener('click', () => this.useCamera());
        document.getElementById('reportBtn').addEventListener('click', () => this.showReportModal());
        document.getElementById('generateReportBtn').addEventListener('click', () => this.generateReport());
    }

    async processMedia() {
        this.showLoading(true);

        try {
            let results;
            if (this.videoElement.srcObject || this.videoElement.src) {
                // Для видео берем текущий кадр
                results = await this.processVideo();
            } else {
                // Для изображения
                results = await this.processImage();
            }

            this.currentResults = results;
            this.displayResults(results);
            this.saveToHistory(results);
            this.updateStatistics(results);

            document.getElementById('reportBtn').disabled = false;
        } catch (error) {
            console.error('Ошибка обработки:', error);
            this.resultsContainer.innerHTML = `
                <div class="alert alert-danger">
                    <h6>Ошибка обработки</h6>
                    <p>${error.message}</p>
                    <small>Проверьте подключение к серверу и формат файла</small>
                </div>
            `;
        } finally {
            this.showLoading(false);
        }
    }

    async processImage() {
        const file = this.fileInput.files[0];
        if (!file) {
            throw new Error('Файл не выбран');
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${this.apiBaseUrl}/api/analyze`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }

            const results = await response.json();

            // Отображение изображения с bounding boxes
            await this.displayImageWithBoxes(file, results);

            return results;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async displayImageWithBoxes(file, results) {
        return new Promise((resolve) => {
            const image = new Image();
            image.onload = () => {
                this.imageCanvas.width = image.width;
                this.imageCanvas.height = image.height;
                this.resultCanvas.width = image.width;
                this.resultCanvas.height = image.height;

                const ctx = this.imageCanvas.getContext('2d');
                ctx.drawImage(image, 0, 0);

                // Отрисовка bounding boxes
                this.drawResultsFromAPI(results);

                resolve();
            };
            image.src = URL.createObjectURL(file);
        });
    }

    drawResultsFromAPI(results) {
        const ctx = this.resultCanvas.getContext('2d');
        ctx.clearRect(0, 0, this.resultCanvas.width, this.resultCanvas.height);

        // Отрисовка ЛЮДЕЙ (желтым цветом) - сначала людей, чтобы они были под столами
        if (results.people && Array.isArray(results.people)) {
            results.people.forEach((person, index) => {
                const bbox = person.bbox;
                const color = '#ffc107'; // Желтый цвет

                // Рисуем bounding box человека (пунктирная линия)
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.setLineDash([5, 3]); // Пунктирная линия
                ctx.strokeRect(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]);
                ctx.setLineDash([]); // Сбрасываем пунктир

                // Заливка с прозрачностью
                ctx.fillStyle = 'rgba(255, 193, 7, 0.1)';
                ctx.fillRect(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]);

                // Подпись для человека
                ctx.fillStyle = color;
                ctx.font = 'bold 14px Arial';
                ctx.fillText(
                    `👤 Человек ${person.id}`,
                    bbox[0], bbox[1] - 5
                );

                // Уверенность детекции
                ctx.font = '12px Arial';
                ctx.fillText(
                    `Уверенность: ${(person.confidence * 100).toFixed(1)}%`,
                    bbox[0], bbox[1] - 25
                );
            });
        }

        // Отрисовка СТОЛОВ (сплошные линии)
        if (results.tables && Array.isArray(results.tables)) {
            results.tables.forEach((table, index) => {
                const bbox = table.bbox;
                const color = table.status === 'occupied' ? '#dc3545' : '#28a745';

                // Рисуем bounding box стола (сплошная линия)
                ctx.strokeStyle = color;
                ctx.lineWidth = 3;
                ctx.strokeRect(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]);

                // Заливка с прозрачностью
                ctx.fillStyle = table.status === 'occupied'
                    ? 'rgba(220, 53, 69, 0.1)'
                    : 'rgba(40, 167, 69, 0.1)';
                ctx.fillRect(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]);

                // Подпись
                ctx.fillStyle = color;
                ctx.font = 'bold 16px Arial';
                const statusText = table.status === 'occupied' ? 'Занят' : 'Свободен';
                ctx.fillText(
                    `🍽️ Стол ${table.id} (${statusText})`,
                    bbox[0], bbox[1] - 5
                );

                // Отображаем количество людей
                if (table.person_count > 0) {
                    ctx.font = '14px Arial';
                    ctx.fillText(
                        `👥 Людей: ${table.person_count}`,
                        bbox[0], bbox[1] - 25
                    );
                }

                // Уверенность детекции
                ctx.font = '12px Arial';
                ctx.fillText(
                    `Уверенность: ${(table.confidence * 100).toFixed(1)}%`,
                    bbox[0], bbox[1] - 45
                );
            });
        }
    }

    async processVideo() {
        // Для видео: берем текущий кадр и отправляем на сервер
        const canvas = document.createElement('canvas');
        canvas.width = this.videoElement.videoWidth;
        canvas.height = this.videoElement.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(this.videoElement, 0, 0, canvas.width, canvas.height);

        // Конвертируем canvas в blob
        return new Promise((resolve, reject) => {
            canvas.toBlob(async (blob) => {
                const formData = new FormData();
                formData.append('file', blob, 'frame.jpg');

                try {
                    const response = await fetch(`${this.apiBaseUrl}/api/analyze`, {
                        method: 'POST',
                        body: formData
                    });

                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                    }

                    const results = await response.json();

                    // Отображение на canvas
                    this.imageCanvas.width = canvas.width;
                    this.imageCanvas.height = canvas.height;
                    this.resultCanvas.width = canvas.width;
                    this.resultCanvas.height = canvas.height;

                    const imgCtx = this.imageCanvas.getContext('2d');
                    imgCtx.drawImage(this.videoElement, 0, 0, canvas.width, canvas.height);

                    this.drawResultsFromAPI(results);

                    resolve(results);
                } catch (error) {
                    reject(error);
                }
            }, 'image/jpeg', 0.8);
        });
    }

    displayResults(results) {
        const occupied = results.tables ? results.tables.filter(t => t.status === 'occupied').length : 0;
        const total = results.tables ? results.tables.length : 0;
        const free = total - occupied;
        const peopleCount = results.people ? results.people.length : 0;

        // Форматируем дату
        const date = new Date(results.timestamp || new Date());
        const formattedDate = date.toLocaleString('ru-RU');

        this.resultsContainer.innerHTML = `
            <div class="alert alert-success">
                <h6>✅ Анализ завершен!</h6>
                <p>Обработано: ${total} столов, ${peopleCount} людей обнаружено</p>
                <small class="text-muted">Время анализа: ${formattedDate}</small>
            </div>

            <div class="row">
                <div class="col-md-6">
                    <h6>🏷️ Состояние столов:</h6>
                    <div class="mb-3" style="max-height: 200px; overflow-y: auto;">
                        ${results.tables && results.tables.length > 0 ? results.tables.map(table => `
                            <div class="table-status ${table.status === 'free' ? 'table-free' : 'table-occupied'} mb-1">
                                Стол ${table.id}: ${table.status === 'free' ? '✅ Свободен' : `❌ Занят (${table.person_count} чел)`}
                                <small class="text-muted d-block">Уверенность: ${(table.confidence * 100).toFixed(1)}%</small>
                            </div>
                        `).join('') : '<p class="text-muted">Столы не обнаружены</p>'}
                    </div>
                </div>

                <div class="col-md-6">
                    <h6>👤 Обнаруженные люди:</h6>
                    <div class="mb-3" style="max-height: 200px; overflow-y: auto;">
                        ${results.people && results.people.length > 0 ? results.people.map(person => `
                            <div class="person-status mb-1 p-2 rounded">
                                👤 Человек ${person.id}
                                <small class="text-muted d-block">Уверенность: ${(person.confidence * 100).toFixed(1)}%</small>
                            </div>
                        `).join('') : '<p class="text-muted">Люди не обнаружены</p>'}
                    </div>
                </div>
            </div>

            <h6>📊 Статистика:</h6>
            <div class="row">
                <div class="col-md-6">
                    <ul class="list-group">
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Всего столов:</span>
                            <strong class="text-primary">${total}</strong>
                        </li>
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Занято столов:</span>
                            <strong class="text-danger">${occupied}</strong>
                        </li>
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Свободно столов:</span>
                            <strong class="text-success">${free}</strong>
                        </li>
                    </ul>
                </div>
                <div class="col-md-6">
                    <ul class="list-group">
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Людей обнаружено:</span>
                            <strong class="text-warning">${peopleCount}</strong>
                        </li>
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Загруженность:</span>
                            <strong>${((results.occupancy_rate || 0) * 100).toFixed(1)}%</strong>
                        </li>
                        <li class="list-group-item d-flex justify-content-between">
                            <span>Уверенность (средняя):</span>
                            <strong>${results.tables && results.tables.length > 0
                                ? (results.tables.reduce((sum, t) => sum + (t.confidence || 0), 0) / results.tables.length * 100).toFixed(1) + '%'
                                : '0%'}</strong>
                        </li>
                    </ul>
                </div>
            </div>

            <div class="mt-3">
                <h6>🖼️ Размер изображения:</h6>
                <p>Ширина: ${results.image_size?.width || 0}px, Высота: ${results.image_size?.height || 0}px</p>
            </div>
        `;
    }

    updateStatistics(results) {
        const tables = results.tables || [];
        const people = results.people || [];
        const occupied = tables.filter(t => t.status === 'occupied').length;
        const total = tables.length;
        const free = total - occupied;
        const occupancyRate = total > 0 ? (occupied / total) : 0;

        this.totalTablesElement.textContent = total;
        this.occupiedTablesElement.textContent = occupied;
        this.freeTablesElement.textContent = free;
        this.peopleCountElement.textContent = people.length;
        this.occupancyBar.style.width = `${occupancyRate * 100}%`;
        this.occupancyPercent.textContent = `${(occupancyRate * 100).toFixed(1)}%`;

        // Меняем цвет прогресс-бара в зависимости от загруженности
        if (occupancyRate < 0.3) {
            this.occupancyBar.className = 'progress-bar bg-success';
        } else if (occupancyRate < 0.7) {
            this.occupancyBar.className = 'progress-bar bg-warning';
        } else {
            this.occupancyBar.className = 'progress-bar bg-danger';
        }
    }

    saveToHistory(results) {
        const historyItem = {
            id: Date.now(),
            ...results,
            image: null // Не сохраняем base64 в историю для экономии места
        };

        this.history.unshift(historyItem);
        if (this.history.length > 50) {
            this.history = this.history.slice(0, 50);
        }

        localStorage.setItem('cafeAnalysisHistory', JSON.stringify(this.history));
        this.loadHistory();
    }

    loadHistory() {
        if (this.history.length === 0) {
            this.historyList.innerHTML = '<p class="text-muted p-3">Нет данных в истории</p>';
            return;
        }

        this.historyList.innerHTML = this.history.map(item => {
            const date = new Date(item.timestamp || new Date());
            const tables = item.tables || [];
            const people = item.people || [];
            const occupied = tables.filter(t => t.status === 'occupied').length;
            const total = tables.length;
            const free = total - occupied;

            return `
                <div class="history-item p-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <small class="text-muted">${date.toLocaleString('ru-RU')}</small>
                            <div class="mt-1">
                                <span class="badge bg-primary">${total} столов</span>
                                <span class="badge bg-danger">${occupied} занято</span>
                                <span class="badge bg-success">${free} свободно</span>
                                <span class="badge bg-warning">${people.length} людей</span>
                            </div>
                        </div>
                        <small class="text-muted">${((item.occupancy_rate || 0) * 100).toFixed(0)}%</small>
                    </div>
                </div>
            `;
        }).join('');
    }

    showReportModal() {
        const modal = new bootstrap.Modal(document.getElementById('reportModal'));
        modal.show();
    }

    async generateReport() {
        const type = document.getElementById('reportType').value;
        const period = document.getElementById('reportPeriod').value;

        try {
            switch(type) {
                case 'pdf':
                    await this.generatePDFReport(period);
                    break;
                case 'summary_pdf':
                    await this.generateSummaryPDFReport(period);
                    break;
                case 'excel':
                    await this.generateExcelReport(period);
                    break;
                case 'json':
                    this.downloadJSONReport(period);
                    break;
            }

            // Показать уведомление об успехе
            this.showNotification('Отчет успешно сформирован!', 'success');
        } catch (error) {
            console.error('Ошибка генерации отчета:', error);
            this.showNotification(`Ошибка генерации отчета: ${error.message}`, 'danger');
        }

        const modal = bootstrap.Modal.getInstance(document.getElementById('reportModal'));
        modal.hide();
    }

    async generatePDFReport(period) {
        try {
            const reportData = this.prepareReportData(period);

            const response = await fetch(`${this.apiBaseUrl}/api/report/pdf`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(reportData)
            });

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('text/html')) {
                    const text = await response.text();
                    throw new Error('Сервер вернул HTML вместо PDF. Возможно, произошла ошибка на сервере.');
                } else {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
            }

            const blob = await response.blob();
            this.downloadBlob(blob, `cafe-report-${period}-${new Date().toISOString().slice(0,10)}.pdf`);
        } catch (error) {
            console.error('Error generating PDF:', error);
            throw error;
        }
    }

    async generateSummaryPDFReport(period) {
        try {
            const reportData = this.prepareReportData(period);

            const response = await fetch(`${this.apiBaseUrl}/api/report/summary_pdf`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(reportData)
            });

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('text/html')) {
                    const text = await response.text();
                    throw new Error('Сервер вернул HTML вместо PDF. Возможно, произошла ошибка на сервере.');
                } else {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
            }

            const blob = await response.blob();
            this.downloadBlob(blob, `cafe-summary-report-${period}-${new Date().toISOString().slice(0,10)}.pdf`);
        } catch (error) {
            console.error('Error generating summary PDF:', error);
            throw error;
        }
    }

    async generateExcelReport(period) {
        try {
            const reportData = this.prepareReportData(period);

            const response = await fetch(`${this.apiBaseUrl}/api/report/excel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(reportData)
            });

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('text/html')) {
                    const text = await response.text();
                    throw new Error('Сервер вернул HTML вместо Excel. Возможно, произошла ошибка на сервере.');
                } else {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
            }

            const blob = await response.blob();
            this.downloadBlob(blob, `cafe-report-${period}-${new Date().toISOString().slice(0,10)}.xlsx`);
        } catch (error) {
            console.error('Error generating Excel:', error);
            throw error;
        }
    }

    prepareReportData(period) {
        let data;
        if (period === 'current') {
            // Текущие результаты
            data = {
                'data': this.currentResults || this.history[0] || {}
            };
        } else {
            // История за период - создаем сводный отчет
            const filteredHistory = this.filterHistoryByPeriod(period);

            // Создаем сводную статистику
            const summary = this.createSummaryReport(filteredHistory);

            data = {
                'data': summary,
                'period': period,
                'history': filteredHistory,
                'summary': true
            };
        }

        return data;
    }

    createSummaryReport(history) {
        if (!history || history.length === 0) {
            return {
                'tables_found': 0,
                'people_found': 0,
                'tables': [],
                'people': [],
                'occupancy_rate': 0,
                'summary': 'Нет данных за выбранный период'
            };
        }

        // Собираем общую статистику
        let totalTables = 0;
        let totalPeople = 0;
        let totalOccupiedTables = 0;
        let totalAnalysis = history.length;

        // Собираем все столы и людей из истории
        const allTables = [];
        const allPeople = [];

        history.forEach(item => {
            if (item.tables && Array.isArray(item.tables)) {
                totalTables += item.tables.length;
                totalOccupiedTables += item.tables.filter(t => t.status === 'occupied').length;

                // Добавляем столы с пометкой времени
                item.tables.forEach(table => {
                    allTables.push({
                        ...table,
                        'analysis_time': item.timestamp,
                        'analysis_id': item.id
                    });
                });
            }

            if (item.people && Array.isArray(item.people)) {
                totalPeople += item.people.length;

                // Добавляем людей с пометкой времени
                item.people.forEach(person => {
                    allPeople.push({
                        ...person,
                        'analysis_time': item.timestamp,
                        'analysis_id': item.id
                    });
                });
            }
        });

        const avgOccupancyRate = totalTables > 0 ? totalOccupiedTables / totalTables : 0;

        return {
            'tables_found': totalTables,
            'people_found': totalPeople,
            'tables': allTables.slice(0, 50), // Берем первые 50 столов для отчета
            'people': allPeople.slice(0, 50), // Берем первых 50 людей для отчета
            'occupancy_rate': avgOccupancyRate,
            'total_analyses': totalAnalysis,
            'avg_tables_per_analysis': totalAnalysis > 0 ? (totalTables / totalAnalysis).toFixed(2) : 0,
            'avg_people_per_analysis': totalAnalysis > 0 ? (totalPeople / totalAnalysis).toFixed(2) : 0,
            'period_start': history[history.length - 1]?.timestamp,
            'period_end': history[0]?.timestamp,
            'summary': `Сводный отчет за период: ${totalAnalysis} анализов`
        };
    }

    downloadJSONReport(period) {
        const filteredHistory = this.filterHistoryByPeriod(period);
        const reportData = {
            period: period,
            generated_at: new Date().toISOString(),
            total_analyses: filteredHistory.length,
            data: filteredHistory
        };

        const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' });
        this.downloadBlob(blob, `cafe-analysis-${period}-${new Date().toISOString().slice(0,10)}.json`);
    }

    filterHistoryByPeriod(period) {
        const now = new Date();
        const filtered = [];

        this.history.forEach(item => {
            const itemDate = new Date(item.timestamp || now);
            let include = false;

            switch(period) {
                case 'day':
                    include = (now - itemDate) <= (24 * 60 * 60 * 1000);
                    break;
                case 'week':
                    include = (now - itemDate) <= (7 * 24 * 60 * 60 * 1000);
                    break;
                case 'all':
                    include = true;
                    break;
                default: // current
                    include = this.currentResults && item.id === this.currentResults.id;
            }

            if (include) {
                filtered.push(item);
            }
        });

        return filtered;
    }

    downloadBlob(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }

    showNotification(message, type = 'info') {
        // Создаем уведомление
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        alert.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(alert);

        // Автоматически скрываем через 3 секунды
        setTimeout(() => {
            if (alert.parentNode) {
                alert.remove();
            }
        }, 3000);
    }

    showLoading(show) {
        this.processBtn.disabled = show;
        document.getElementById('processText').style.display = show ? 'none' : 'inline';
        document.getElementById('processSpinner').style.display = show ? 'inline-block' : 'none';
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.processBtn.disabled = false;

        if (file.type.startsWith('image/')) {
            this.videoElement.style.display = 'none';
            this.imageCanvas.style.display = 'block';
            this.resultCanvas.style.display = 'block';
            document.getElementById('noMedia').style.display = 'none';

            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    this.imageCanvas.width = img.width;
                    this.imageCanvas.height = img.height;
                    this.resultCanvas.width = img.width;
                    this.resultCanvas.height = img.height;

                    const ctx = this.imageCanvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);

                    // Очищаем результат canvas
                    const resultCtx = this.resultCanvas.getContext('2d');
                    resultCtx.clearRect(0, 0, this.resultCanvas.width, this.resultCanvas.height);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);

        } else if (file.type.startsWith('video/')) {
            this.imageCanvas.style.display = 'none';
            this.resultCanvas.style.display = 'none';
            this.videoElement.style.display = 'block';
            document.getElementById('noMedia').style.display = 'none';

            this.videoElement.src = URL.createObjectURL(file);
            this.videoElement.load();
        }
    }

    useCamera() {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => {
                this.videoElement.style.display = 'block';
                this.imageCanvas.style.display = 'none';
                this.resultCanvas.style.display = 'none';
                document.getElementById('noMedia').style.display = 'none';
                this.videoElement.srcObject = stream;
                this.processBtn.disabled = false;
                this.showNotification('Камера активирована! Нажмите "Запустить анализ" для обработки кадра.', 'info');
            })
            .catch(err => {
                console.error('Ошибка доступа к камере:', err);
                this.showNotification('Не удалось получить доступ к камере', 'danger');
            });
    }
}

// Инициализация приложения
document.addEventListener('DOMContentLoaded', () => {
    window.analyzer = new CafeTableAnalyzer();

    // Проверка подключения к серверу
    fetch('http://localhost:5000/health')
        .then(response => response.json())
        .then(data => {
            console.log('Сервер доступен:', data);
        })
        .catch(error => {
            console.error('Сервер недоступен:', error);
            window.analyzer.showNotification('Сервер анализа недоступен. Запустите server.py', 'warning');
        });
});
