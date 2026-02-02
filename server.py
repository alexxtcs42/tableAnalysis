from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import cv2
import numpy as np
import json
import os
from datetime import datetime
import pandas as pd
from werkzeug.utils import secure_filename
import torch
from ultralytics import YOLO
import supervision as sv
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping


app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Загрузка предобученных моделей
person_model = YOLO('models/yolov8n.pt')
table_model = YOLO('models/yolov8n.pt')


def load_models():
    global person_model, table_model
    try:
        # YOLOv8 для детектирования людей
        person_model = YOLO('models/yolov8n.pt')

        # YOLOv8 для детектирования столов
        table_model = YOLO('models/yolov8n.pt')

        print("Модели загружены успешно")
        return True
    except Exception as e:
        print(f"Ошибка загрузки моделей: {e}")
        return False


# База данных для хранения истории
HISTORY_FILE = 'analysis_history.json'


def save_to_history(data):
    """Сохранение результатов в JSON файл"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            history = json.load(f)
    else:
        history = []

    history.append({
        'timestamp': datetime.now().isoformat(),
        'data': data
    })

    with open(HISTORY_FILE, 'w') as f:
        json.dump(history[-100:], f, indent=2)  # Храним 100 последних записей


def register_russian_fonts():
    """Регистрация шрифтов с поддержкой кириллицы"""
    try:
        # Путь к шрифту (можно использовать стандартные или добавить свой)
        font_path = None

        # Проверяем доступные системные шрифты
        possible_fonts = [
            'DejaVuSans.ttf',  # Распространённый свободный шрифт
            'arial.ttf',  # Windows
            'LiberationSans-Regular.ttf',  # Linux
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux
            'C:\\Windows\\Fonts\\arial.ttf',  # Windows
        ]

        for font in possible_fonts:
            if os.path.exists(font):
                font_path = font
                break

        # Если шрифт не найден, используем стандартный (может не поддерживать кириллицу)
        if font_path:
            pdfmetrics.registerFont(TTFont('RussianFont', font_path))
            pdfmetrics.registerFont(TTFont('RussianFont-Bold', font_path))
            addMapping('RussianFont', 0, 0, 'RussianFont')
            addMapping('RussianFont', 1, 0, 'RussianFont-Bold')
            return True
        return False
    except Exception:
        return False


def calculate_iou(box1, box2, epsilon=1e-6):
    """
    Calculate Intersection over Union (IoU) for two bounding boxes
    Формат: [x_min, y_min, x_max, y_max]
    epsilon: маленькое значение для избежания деления на ноль
    """
    # Проверка на валидность bounding boxes
    if box1[2] <= box1[0] or box1[3] <= box1[1]:
        return 0.0
    if box2[2] <= box2[0] or box2[3] <= box2[1]:
        return 0.0

    # Координаты пересечения
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    # Проверка на пересечение
    if x2 < x1 or y2 < y1:
        return 0.0

    # Вычисление площадей
    intersection_area = (x2 - x1) * (y2 - y1)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])

    # IoU с защитой от деления на ноль (используем epsilon)
    union_area = box1_area + box2_area - intersection_area
    if union_area <= 0:
        return 0.0

    iou = intersection_area / (union_area + epsilon)  # Теперь используем epsilon
    return iou


@app.route('/api/analyze', methods=['POST'])
def analyze_image():
    """Анализ загруженного изображения"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Проверяем, что модели загружены
    if person_model is None or table_model is None:
        if not load_models():
            return jsonify({'error': 'Models failed to load'}), 500

    # Сохранение файла
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        # Загрузка изображения
        image = cv2.imread(filepath)
        if image is None:
            return jsonify({'error': 'Failed to load image'}), 400

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Детектирование столов - используем модель правильно
        table_results = table_model.predict(image_rgb, conf=0.11, iou=0.10)[0]
        table_detections = sv.Detections.from_ultralytics(table_results)

        # Детектирование людей
        person_results = person_model.predict(image_rgb, conf=0.15, iou=0.15)[0]
        person_detections = sv.Detections.from_ultralytics(person_results)

        # Фильтрация только столов (класс 60 в COCO - dining table)
        table_detections = table_detections[table_detections.class_id == 60]

        # Фильтрация только людей (класс 0 в COCO - person)
        person_detections = person_detections[person_detections.class_id == 0]

        # Формирование данных о людях
        people_data = []
        for i, person_box in enumerate(person_detections.xyxy):
            person_box = person_box.tolist()
            people_data.append({
                'id': i + 1,
                'bbox': person_box,
                'confidence': float(person_detections.confidence[i]) if i < len(person_detections.confidence) else 0.0
            })

        # Анализ занятости столов
        tables_data = []
        for i, table_box in enumerate(table_detections.xyxy):
            table_box = table_box.tolist()

            # Проверка, есть ли люди рядом со столом
            is_occupied = False
            person_count = 0
            iou_sum = 0

            for person_box in person_detections.xyxy:
                person_box = person_box.tolist()

                # Простая логика пересечения bounding boxes
                table_center = (table_box[0] + table_box[2]) / 2
                person_center = (person_box[0] + person_box[2]) / 2

                distance = abs(table_center - person_center)

                # Динамический порог на основе размера стола
                table_width = table_box[2] - table_box[0]
                threshold = table_width * 0.75
                iou = calculate_iou(table_box, person_box)
                iou_sum += iou

                if distance < threshold:
                    is_occupied = True
                    if iou > 0:
                        person_count += 1

            if not (iou_sum > 0.3 or person_count > 2 or (iou_sum > 0.2 and person_count > 1)):
                is_occupied = False

            tables_data.append({
                'id': i + 1,
                'bbox': table_box,
                'status': 'occupied' if is_occupied else 'free',
                'person_count': person_count,
                'confidence': float(table_detections.confidence[i]) if i < len(table_detections.confidence) else 0.0
            })

        # Подготовка результатов
        results = {
            'timestamp': datetime.now().isoformat(),
            'tables_found': len(tables_data),
            'people_found': len(people_data),
            'tables': tables_data,
            'people': people_data,
            'occupancy_rate': sum(1 for t in tables_data if t['status'] == 'occupied') / max(len(tables_data), 1),
            'image_size': {'width': image.shape[1], 'height': image.shape[0]}
        }

        # Сохранение в историю
        save_to_history(results)

        return jsonify(results)

    except Exception as e:
        print(f"Error during analysis: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        # Очистка временных файлов
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/api/history', methods=['GET'])
def get_history():
    """Получение истории анализов"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            history = json.load(f)
        return jsonify(history)
    return jsonify([])


@app.route('/api/report/pdf', methods=['POST'])
def generate_pdf_report():
    """Генерация PDF отчета"""
    data = request.json

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors

    # Регистрируем русские шрифты
    font_registered = register_russian_fonts()

    os.makedirs('reports', exist_ok=True)

    filename = f"cafe_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join('reports', filename)

    c = canvas.Canvas(filepath, pagesize=A4)

    # Устанавливаем шрифт с поддержкой кириллицы
    if font_registered:
        c.setFont("RussianFont", 16)
    else:
        c.setFont("Helvetica", 16)  # Fallback

    c.drawString(50, 800, "Отчет по анализу использования столов в кафе")

    if font_registered:
        c.setFont("RussianFont", 12)
    else:
        c.setFont("Helvetica", 12)

    c.drawString(50, 750, f"Дата генерации: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if 'data' in data:
        stats = data['data']
        c.drawString(50, 700, f"Проанализировано столов: {stats.get('tables_found', 0)}")
        c.drawString(50, 680, f"Обнаружено людей: {stats.get('people_found', 0)}")
        c.drawString(50, 660, f"Загруженность: {stats.get('occupancy_rate', 0) * 100:.1f}%")

        # Добавляем информацию о людях
        c.drawString(50, 630, "Детализация по людям:")
        y_pos = 610
        if 'people' in stats and stats['people']:
            for person in stats['people'][:10]:
                c.drawString(70, y_pos,
                             f"Человек {person.get('id', '')}: уверенность {person.get('confidence', 0) * 100:.1f}%")
                y_pos -= 20
                if y_pos < 50:
                    break

    c.save()

    return send_file(filepath, as_attachment=True)


@app.route('/api/report/summary_pdf', methods=['POST'])
def generate_summary_pdf_report():
    """Генерация PDF отчета со сводной статистикой"""
    data = request.json

    # Регистрируем русские шрифты
    font_registered = register_russian_fonts()

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab.rl_config

    os.makedirs('reports', exist_ok=True)

    filename = f"cafe_summary_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join('reports', filename)

    # Создаем стили с поддержкой кириллицы
    styles = getSampleStyleSheet()

    # Определяем имя шрифта в зависимости от регистрации
    font_name = "RussianFont" if font_registered else "Helvetica"
    bold_font_name = "RussianFont-Bold" if font_registered else "Helvetica-Bold"

    # Создаем кастомные стили с русским шрифтом
    if font_registered:
        # Стиль для заголовка
        styles.add(ParagraphStyle(
            name='RussianHeading1',
            parent=styles['Heading1'],
            fontName=bold_font_name,
            fontSize=16,
            spaceAfter=12
        ))

        # Стиль для подзаголовка
        styles.add(ParagraphStyle(
            name='RussianHeading2',
            parent=styles['Heading2'],
            fontName=bold_font_name,
            fontSize=14,
            spaceAfter=8
        ))

        # Стиль для обычного текста
        styles.add(ParagraphStyle(
            name='RussianNormal',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10
        ))

        # Стиль для метаданных
        styles.add(ParagraphStyle(
            name='RussianMetadata',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=9,
            textColor=colors.grey
        ))
    else:
        # Fallback стили с английским текстом
        styles.add(ParagraphStyle(
            name='RussianHeading1',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=12
        ))
        styles.add(ParagraphStyle(
            name='RussianHeading2',
            parent=styles['Heading2'],
            fontSize=14,
            spaceAfter=8
        ))
        styles.add(ParagraphStyle(
            name='RussianNormal',
            parent=styles['Normal'],
            fontSize=10
        ))
        styles.add(ParagraphStyle(
            name='RussianMetadata',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey
        ))

    doc = SimpleDocTemplate(filepath, pagesize=A4)
    elements = []

    # Заголовок отчета
    if font_registered:
        elements.append(Paragraph("Сводный отчет по использованию столов в кафе", styles['RussianHeading1']))
    else:
        elements.append(Paragraph("Cafe Table Usage Summary Report", styles['RussianHeading1']))

    elements.append(Spacer(1, 12))

    if 'data' in data:
        stats = data['data']

        # Основная информация
        if font_registered:
            elements.append(Paragraph(f"<b>Период:</b> {data.get('period', 'текущий')}", styles['RussianNormal']))
            elements.append(Paragraph(f"<b>Сгенерировано:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                                      styles['RussianNormal']))
            elements.append(
                Paragraph(f"<b>Количество анализов:</b> {stats.get('total_analyses', 1)}", styles['RussianNormal']))
        else:
            elements.append(Paragraph(f"<b>Period:</b> {data.get('period', 'current')}", styles['RussianNormal']))
            elements.append(
                Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['RussianNormal']))
            elements.append(
                Paragraph(f"<b>Number of analyses:</b> {stats.get('total_analyses', 1)}", styles['RussianNormal']))

        elements.append(Spacer(1, 20))

        # Статистика
        if font_registered:
            table_data = [
                ['Показатель', 'Значение'],
                ['Всего столов обнаружено', stats.get('tables_found', 0)],
                ['Всего людей обнаружено', stats.get('people_found', 0)],
                ['Общая загруженность', f"{stats.get('occupancy_rate', 0) * 100:.1f}%"],
                ['Среднее столов на анализ', f"{stats.get('avg_tables_per_analysis', 0):.1f}"],
                ['Среднее людей на анализ', f"{stats.get('avg_people_per_analysis', 0):.1f}"]
            ]
        else:
            table_data = [
                ['Metric', 'Value'],
                ['Total tables detected', stats.get('tables_found', 0)],
                ['Total people detected', stats.get('people_found', 0)],
                ['Overall occupancy rate', f"{stats.get('occupancy_rate', 0) * 100:.1f}%"],
                ['Average tables per analysis', f"{stats.get('avg_tables_per_analysis', 0):.1f}"],
                ['Average people per analysis', f"{stats.get('avg_people_per_analysis', 0):.1f}"]
            ]

        table = Table(table_data, colWidths=[200, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A6572')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), bold_font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F0F0F0')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 25))

        # Подробная таблица столов (если есть)
        if 'tables' in stats and stats['tables']:
            if font_registered:
                elements.append(Paragraph("Детализация по столам:", styles['RussianHeading2']))
                tables_data = [['ID', 'Статус', 'Людей', 'Уверенность', 'Время анализа']]
            else:
                elements.append(Paragraph("Tables Details:", styles['RussianHeading2']))
                tables_data = [['ID', 'Status', 'People', 'Confidence', 'Analysis Time']]

            elements.append(Spacer(1, 5))

            for table in stats['tables'][:20]:  # Ограничиваем 20 записями
                if font_registered:
                    status_text = 'Занят' if table.get('status') == 'occupied' else 'Свободен'
                else:
                    status_text = 'Occupied' if table.get('status') == 'occupied' else 'Free'

                tables_data.append([
                    table.get('id', ''),
                    status_text,
                    table.get('person_count', 0),
                    f"{table.get('confidence', 0) * 100:.1f}%",
                    table.get('analysis_time', '')[:19] if table.get('analysis_time') else ''
                ])

            if len(stats['tables']) > 20:
                if font_registered:
                    tables_data.append(['', f'... и еще {len(stats["tables"]) - 20} записей', '', '', ''])
                else:
                    tables_data.append(['', f'... and {len(stats["tables"]) - 20} more', '', '', ''])

            tables_table = Table(tables_data, colWidths=[40, 60, 50, 70, 110])
            tables_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5D9CEC')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
                ('FONTNAME', (0, 0), (-1, 0), bold_font_name),
                ('FONTNAME', (0, 1), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ]))

            elements.append(tables_table)
            elements.append(Spacer(1, 20))

        # Подробная таблица людей (если есть)
        if 'people' in stats and stats['people']:
            if font_registered:
                elements.append(Paragraph("Детализация по людям:", styles['RussianHeading2']))
                people_data = [['ID', 'Уверенность', 'Координаты', 'Время анализа']]
            else:
                elements.append(Paragraph("People Details:", styles['RussianHeading2']))
                people_data = [['ID', 'Confidence', 'Coordinates', 'Analysis Time']]

            elements.append(Spacer(1, 5))

            for person in stats['people'][:15]:  # Ограничиваем 15 записями
                bbox = person.get('bbox', [0, 0, 0, 0])
                people_data.append([
                    person.get('id', ''),
                    f"{person.get('confidence', 0) * 100:.1f}%",
                    f"[{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}]",
                    person.get('analysis_time', '')[:19] if person.get('analysis_time') else ''
                ])

            if len(stats['people']) > 15:
                if font_registered:
                    people_data.append(['', f'... и еще {len(stats["people"]) - 15} записей', '', ''])
                else:
                    people_data.append(['', f'... and {len(stats["people"]) - 15} more', '', ''])

            people_table = Table(people_data, colWidths=[30, 70, 110, 110])
            people_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FFCE54')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#333333')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
                ('FONTNAME', (0, 0), (-1, 0), bold_font_name),
                ('FONTNAME', (0, 1), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ]))

            elements.append(people_table)
            elements.append(Spacer(1, 20))

        # Сводная информация
        if font_registered:
            elements.append(Paragraph("Сводная информация:", styles['RussianHeading2']))

            summary_elements = []
            if stats.get('period_start'):
                summary_elements.append(f"Начало периода: {stats['period_start'][:19]}")
            if stats.get('period_end'):
                summary_elements.append(f"Конец периода: {stats['period_end'][:19]}")
            if stats.get('summary'):
                summary_elements.append(f"Описание: {stats['summary']}")

            if summary_elements:
                for item in summary_elements:
                    elements.append(Paragraph(f"• {item}", styles['RussianMetadata']))
        else:
            elements.append(Paragraph("Summary Information:", styles['RussianHeading2']))

            summary_elements = []
            if stats.get('period_start'):
                summary_elements.append(f"Period start: {stats['period_start'][:19]}")
            if stats.get('period_end'):
                summary_elements.append(f"Period end: {stats['period_end'][:19]}")
            if stats.get('summary'):
                summary_elements.append(f"Description: {stats['summary']}")

            if summary_elements:
                for item in summary_elements:
                    elements.append(Paragraph(f"• {item}", styles['RussianMetadata']))

    else:
        if font_registered:
            elements.append(Paragraph("Данные для отчета не предоставлены.", styles['RussianNormal']))
        else:
            elements.append(Paragraph("No data provided for the report.", styles['RussianNormal']))

    # Подвал с информацией о системе
    elements.append(Spacer(1, 30))
    if font_registered:
        footer_text = f"Отчет сгенерирован системой AI Cafe Analytics • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    else:
        footer_text = f"Report generated by AI Cafe Analytics • {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    elements.append(Paragraph(footer_text, ParagraphStyle(
        name='Footer',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER
    )))

    try:
        doc.build(elements)
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/excel', methods=['POST'])
def generate_excel_report():
    """Генерация Excel отчета"""
    data = request.json

    os.makedirs('reports', exist_ok=True)

    # Создаем DataFrame для столов
    tables_data = []
    if 'data' in data and 'tables' in data['data']:
        for table in data['data']['tables']:
            tables_data.append({
                'ID стола': table['id'],
                'Статус': 'Занят' if table['status'] == 'occupied' else 'Свободен',
                'Количество людей': table['person_count'],
                'Уверенность': f"{table['confidence']:.2%}",
                'Координаты': f"[{table['bbox'][0]:.1f}, {table['bbox'][1]:.1f},"
                              f" {table['bbox'][2]:.1f}, {table['bbox'][3]:.1f}]"
            })

    # Создаем DataFrame для людей
    people_data = []
    if 'data' in data and 'people' in data['data']:
        for person in data['data']['people']:
            people_data.append({
                'ID человека': person['id'],
                'Уверенность': f"{person['confidence']:.2%}",
                'Координаты X1': f"{person['bbox'][0]:.1f}",
                'Координаты Y1': f"{person['bbox'][1]:.1f}",
                'Координаты X2': f"{person['bbox'][2]:.1f}",
                'Координаты Y2': f"{person['bbox'][3]:.1f}"
            })

    filename = f"cafe_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join('reports', filename)

    # Сохранение в Excel с несколькими листами
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        if tables_data:
            pd.DataFrame(tables_data).to_excel(writer, sheet_name='Столы', index=False)
        if people_data:
            pd.DataFrame(people_data).to_excel(writer, sheet_name='Люди', index=False)

        # Добавляем суммарный лист
        summary_data = {
            'Показатель': ['Всего столов', 'Всего людей', 'Загруженность', 'Дата отчета'],
            'Значение': [
                len(tables_data),
                len(people_data),
                f"{data.get('data', {}).get('occupancy_rate', 0) * 100:.1f}%" if 'data' in data else "0%",
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Сводка', index=False)

    return send_file(filepath, as_attachment=True)


@app.route('/health', methods=['GET'])
def health_check():
    """Проверка состояния сервера"""
    return jsonify({
        'status': 'healthy',
        'models_loaded': person_model is not None and table_model is not None,
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    # Создание необходимых директорий
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    os.makedirs('models', exist_ok=True)

    # Загрузка моделей при запуске
    if not load_models():
        print("Warning: Models failed to load. The server will attempt to load them on first request.")

    app.run(debug=True, port=5000)
