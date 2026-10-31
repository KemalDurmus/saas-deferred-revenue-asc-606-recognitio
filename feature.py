from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

import logic

bp = Blueprint('feature', __name__)


def _defaults():
    return {'default_months': '12', 'report_month': date.today().strftime('%Y-%m'), 'csv_text': ''}


@bp.route('/', methods=['GET'])
def index():
    return render_template('index.html', form=_defaults(), result=None, demo=False)


@bp.route('/analyze', methods=['GET', 'POST'])
def analyze():
    if request.method == 'GET':
        return redirect(url_for('feature.index'))
    form = _defaults()
    form['default_months'] = request.form.get('default_months', '12')
    form['report_month'] = request.form.get('report_month', '') or form['report_month']
    form['csv_text'] = request.form.get('csv_text', '')
    demo = request.form.get('demo') == '1'
    result = None
    try:
        warnings = []
        if demo:
            text = logic.demo_csv()
            form['csv_text'] = ''
        else:
            upload = request.files.get('csv_file')
            if upload is not None and upload.filename:
                raw = upload.read(logic.MAX_BYTES + 1)
                text, warnings = logic.decode_bytes(raw)
            elif form['csv_text'].strip():
                text, warnings = logic.decode_bytes(form['csv_text'].encode('utf-8'))
            else:
                raise logic.InputError('Lütfen bir CSV dosyası yükleyin, içeriği yapıştırın ya da "Örnek veriyle dene" düğmesini kullanın.')
        result = logic.analyze(text, form['default_months'], form['report_month'])
        result['warnings'] = warnings + result['warnings']
    except logic.InputError as e:
        flash(str(e), 'error')
    except Exception:
        flash('Veri işlenirken beklenmeyen bir sorun oluştu. Dosyanın Stripe/Paddle CSV biçiminde olduğunu kontrol edip tekrar deneyin.', 'error')
    return render_template('index.html', form=form, result=result, demo=demo and result is not None)
