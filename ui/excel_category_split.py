"""Three-step category splitter; background work never changes an unconfirmed source."""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QListWidget,
    QListWidgetItem, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QAbstractItemView, QFrame, QScrollArea,
)
from excel_category_split import (
    SplitOptions, source_info, inspect_source, build_preview,
    select_groups, export_split,
)
from ui.tasks import BackgroundTaskThread
from ui.common_widgets import SelectionComboBox, ClearSpinBox


class CategorySplitPage(QWidget):
    def __init__(self, parent=None, inspect_fn=inspect_source,
                 preview_fn=build_preview, export_fn=export_split):
        super().__init__(parent)
        self.inspect_fn=inspect_fn; self.preview_fn=preview_fn;self.export_fn=export_fn
        self.busy=False;self.preview=None;self.result=None;self.confirmed_preview=None
        self._loaded_source=None; self._thread=None;self._error=None;self._payload=None
        self._column_signature=None; self._column_digest=None
        self.setObjectName('categorySplitPage')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,12,0,0);layout.setSpacing(10)
        step_row=QHBoxLayout();step_row.setSpacing(10);self.step_badges=[]
        for text in ('01  选择数据','02  设置分类','03  核对结果'):
            badge=QLabel(text);badge.setProperty('splitStep',True);step_row.addWidget(badge,1);self.step_badges.append(badge)
        layout.addLayout(step_row)
        self.step_label=QLabel();self.step_label.setProperty('role','subtitle');self.step_label.hide()
        self.steps=QStackedWidget();layout.addWidget(self.steps,1)
        first=QWidget();form=QFormLayout(first);form.setSpacing(14);form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.source_edit=QLineEdit();self.source_edit.setPlaceholderText('选择本地 .xlsx 文件')
        browse=QPushButton('选择文件');browse.clicked.connect(self.choose_source)
        self.load_button=QPushButton('重新读取');self.load_button.clicked.connect(self.load_source)
        row=QHBoxLayout();row.addWidget(self.source_edit,1);row.addWidget(browse);row.addWidget(self.load_button)
        form.addRow('源文件',row)
        self.sheet_combo=SelectionComboBox();form.addRow('工作表',self.sheet_combo)
        self.range_combo=SelectionComboBox();self.range_combo.addItems(['整个工作表','指定区域'])
        self.area_edit=QLineEdit();self.area_edit.setPlaceholderText('例如 A3:H500');self.area_edit.setEnabled(False)
        row=QHBoxLayout();row.addWidget(self.range_combo);row.addWidget(self.area_edit,1);form.addRow('处理范围',row)
        self.header_spin=ClearSpinBox();self.header_spin.setRange(0,1048575);self.header_spin.setValue(1);self.header_spin.setSuffix(' 行');self.header_spin.setMaximumWidth(160)
        form.addRow('表头行数',self.header_spin)
        hint=QLabel('所选区域开头的表头行会复制到每份结果。数据默认全部参与；发现筛选或隐藏行时，会提示选择处理范围。\n请先在 Excel 中完成计算并保存；原文件保持不变。')
        hint.setWordWrap(True);hint.setProperty('role','hint');form.addRow(hint)
        self.add_card(first,'选择要拆分的数据','先选择文件，再指定工作表和表头。')
        second=QWidget();form=QFormLayout(second);form.setSpacing(12);form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.column_list=QListWidget();self.column_list.setMinimumHeight(130);self.column_list.setMaximumHeight(180)
        form.addRow('选择分类列（可多选）',self.column_list)
        self.trim_check=QCheckBox('忽略分类名称首尾空格（不改变导出的原始文字）');form.addRow(self.trim_check)
        self.mode_combo=SelectionComboBox();self.mode_combo.addItem('每类一个文件','files');self.mode_combo.addItem('每类一个工作表','sheets')
        form.addRow('保存方式',self.mode_combo)
        mode_hint=QLabel('每类一个文件：分别保存为 Excel 文件。\n每类一个工作表：保存在同一个新 Excel 文件中。');mode_hint.setWordWrap(True);mode_hint.setProperty('role','hint');form.addRow(mode_hint)
        self.output_edit=QLineEdit();self.output_edit.setPlaceholderText('选择结果保存文件夹')
        output_browse=QPushButton('选择文件夹');output_browse.clicked.connect(self.choose_output)
        row=QHBoxLayout();row.addWidget(self.output_edit,1);row.addWidget(output_browse);form.addRow('保存位置',row)
        hint=QLabel('所选列内容相同的行分为一类，自动使用分类名称命名。空白分类保留，完全空白行跳过。\n保留各行基本格式，公式转为文件中已保存的固定结果。')
        hint.setWordWrap(True);hint.setProperty('role','hint');form.addRow(hint);self.add_card(second,'设置分类与保存方式','勾选一列或多列，相同内容会归入同一类。')
        third=QWidget();v=QVBoxLayout(third);v.setContentsMargins(0,0,0,0);v.setSpacing(14)
        metrics=QHBoxLayout();self.metric_labels=[]
        for _ in range(3):
            label=QLabel();label.setProperty('splitMetric',True);metrics.addWidget(label,1);self.metric_labels.append(label)
        v.addLayout(metrics)
        self.summary_label=QLabel();self.summary_label.setWordWrap(True);self.summary_label.setTextFormat(Qt.PlainText);v.addWidget(self.summary_label)
        row=QHBoxLayout();self.all_button=QPushButton('全选');self.none_button=QPushButton('取消全选')
        self.all_button.clicked.connect(lambda:self.set_all(True));self.none_button.clicked.connect(lambda:self.set_all(False))
        row.addWidget(self.all_button);row.addWidget(self.none_button);row.addStretch();v.addLayout(row)
        self.category_table=QTableWidget(0,4);self.category_table.setHorizontalHeaderLabels(['导出','分类','记录数','最终名称'])
        self.category_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.category_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.category_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        self.category_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.category_table.setShowGrid(False);self.category_table.setAlternatingRowColors(True)
        self.category_table.verticalHeader().hide();self.category_table.verticalHeader().setDefaultSectionSize(36)
        self.category_table.setMinimumHeight(180)
        v.addWidget(self.category_table,1);self.add_card(third,'核对分类结果','可取消不需要导出的类别，确认后生成全新文件。')
        self.status_label=QLabel('尚未选择文件');self.status_label.setWordWrap(True);self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setProperty('role','hint');layout.addWidget(self.status_label)
        buttons=QHBoxLayout();self.back_button=QPushButton('上一步');self.next_button=QPushButton('下一步');self.next_button.setProperty('variant','primary')
        self.confirm_button=QPushButton('开始拆分');self.confirm_button.setProperty('variant','primary')
        self.open_button=QPushButton('打开结果文件夹');self.open_button.hide()
        for b in (self.back_button,self.next_button,self.confirm_button,self.open_button):b.setMinimumHeight(38)
        self.back_button.clicked.connect(self.go_back);self.next_button.clicked.connect(self.go_next)
        self.confirm_button.clicked.connect(self.confirm_export);self.open_button.clicked.connect(self.open_result)
        buttons.addWidget(self.back_button);buttons.addStretch();buttons.addWidget(self.open_button);buttons.addWidget(self.next_button);buttons.addWidget(self.confirm_button)
        footer=QFrame();footer.setObjectName('splitFooter');footer.setLayout(buttons);layout.addWidget(footer)
        self.source_edit.textChanged.connect(self.source_changed)
        for signal in (self.sheet_combo.currentTextChanged,self.range_combo.currentIndexChanged,
                       self.area_edit.textChanged,self.header_spin.valueChanged,self.trim_check.toggled,
                       self.mode_combo.currentIndexChanged,self.output_edit.textChanged,self.column_list.itemChanged):
            signal.connect(self.invalidate)
        self.range_combo.currentIndexChanged.connect(lambda i:self.area_edit.setEnabled(i==1))
        self.category_table.itemChanged.connect(self.selection_changed)
        self.update_step()

    def add_card(self, content, title, subtitle):
        card=QFrame();card.setProperty('splitCard',True)
        box=QVBoxLayout(card);box.setContentsMargins(20,16,20,16);box.setSpacing(10)
        heading=QLabel(title);heading.setProperty('splitHeading',True);box.addWidget(heading)
        hint=QLabel(subtitle);hint.setProperty('role','hint');hint.setWordWrap(True);box.addWidget(hint)
        box.addWidget(content,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(card);self.steps.addWidget(scroll)

    def source_changed(self):
        self._loaded_source=None;self._column_signature=None;self.sheet_combo.clear();self.invalidate()

    def invalidate(self, *_):
        self.preview=None;self.confirmed_preview=None;self.result=None
        self.confirm_button.setEnabled(False);self.open_button.hide()

    def choose_source(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 Excel 文件','','Excel 文件 (*.xlsx)')
        if path:self.source_edit.setText(path);self.load_source()

    def choose_output(self):
        path=QFileDialog.getExistingDirectory(self,'选择结果保存文件夹',self.output_edit.text())
        if path:self.output_edit.setText(path)

    def run_job(self, worker, completed):
        if self.busy:return
        self.busy=True;self.setEnabled(False);self._payload=None;self._error=None
        self._thread=BackgroundTaskThread(worker,self)
        self._thread.completed.connect(self._got_payload)
        self._thread.failed.connect(self._got_error)
        self._thread.progress.connect(lambda a,b,text:self.status_label.setText(text))
        def finished():
            thread=self._thread;self._thread=None;self.busy=False;self.setEnabled(True)
            thread.deleteLater()
            if self._error:self.show_error(self._error)
            else:
                try:completed(self._payload)
                except Exception as exc:self.show_error(str(exc))
        self._thread.finished.connect(finished);self._thread.start()

    def _got_payload(self,value):self._payload=value
    def _got_error(self,error):self._error=error

    def show_error(self,message):
        self.status_label.setText('未执行／未完成：'+message)
        self.confirm_button.setEnabled(False)

    def load_source(self):
        path=self.source_edit.text().strip()
        if not path:self.show_error('请先选择文件。');return
        self.invalidate();self.status_label.setText('正在读取工作表…')
        # Only names here: sheets with one title row still need to be selectable.
        def load(progress):
            from excel_category_split import _read_bytes, _open
            wb=_open(_read_bytes(path),read_only=True,data_only=True)
            try:return tuple(wb.sheetnames)
            finally:wb.close()
        def done(names):
            self.sheet_combo.clear();self.sheet_combo.addItems(names);self._loaded_source=path
            if not self.output_edit.text():self.output_edit.setText(str(Path(path).parent))
            self.status_label.setText('已读取。请选择工作表、处理范围和表头。')
        self.run_job(load,done)

    def options(self):
        if self._loaded_source!=self.source_edit.text().strip():
            raise ValueError('请先读取当前文件。')
        keys=tuple(self.column_list.item(i).data(Qt.UserRole) for i in range(self.column_list.count())
                   if self.column_list.item(i).checkState()==Qt.Checked)
        if self.range_combo.currentIndex()==1 and not self.area_edit.text().strip():
            raise ValueError('请填写指定区域，例如 A3:H500。')
        return SplitOptions(Path(self._loaded_source),self.sheet_combo.currentText(),
                            self.area_edit.text().strip() if self.range_combo.currentIndex()==1 else None,
                            self.header_spin.value(),keys,self.trim_check.isChecked(),False,
                            self.mode_combo.currentData(),Path(self.output_edit.text().strip()))

    def go_next(self):
        if self.busy:return
        try:options=self.options()
        except Exception as exc:self.show_error(str(exc));return
        if self.steps.currentIndex()==0:
            signature=(options.source,options.sheet,options.area,options.header_rows)
            old={self.column_list.item(i).data(Qt.UserRole) for i in range(self.column_list.count())
                 if self.column_list.item(i).checkState()==Qt.Checked} if signature==self._column_signature else set()
            def done(info):
                _,labels,digest=info;self._column_digest=digest;self.column_list.clear()
                for col,label in labels:
                    item=QListWidgetItem(label);item.setData(Qt.UserRole,col)
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if col in old else Qt.Unchecked)
                    self.column_list.addItem(item)
                self._column_signature=signature;self.steps.setCurrentIndex(1);self.update_step()
            self.run_job(lambda progress:source_info(options.source,options.sheet,options.area,options.header_rows),done)
        else:
            if not options.key_columns:self.show_error('请至少勾选一个分类列。');return
            if not self.output_edit.text().strip():self.show_error('请选择保存文件夹。');return
            self.status_label.setText('正在检查数据、公式和隐藏行…')
            self.run_job(lambda progress:self.inspect_fn(options),self.snapshot_ready)

    def snapshot_ready(self,snapshot):
        if snapshot.source_sha256 != self._column_digest:
            self.invalidate();self.show_error("源文件已变化，请返回第一步重新读取和选择分类列。");return
        options=snapshot.options
        if snapshot.has_filter or snapshot.has_hidden:
            choice=self.ask_visibility(snapshot)
            if choice is None:self.status_label.setText('已取消，未生成文件。');return
            if choice:
                options=replace(options,visible_only=True)
                self.run_job(lambda progress:self.preview_fn(self.inspect_fn(options),options),self.show_preview)
                return
        self.run_job(lambda progress:self.preview_fn(snapshot,options),self.show_preview)

    def ask_visibility(self,snapshot):
        box=QMessageBox(self);box.setWindowTitle('检测到筛选或隐藏行')
        box.setText('是否仅拆分可见行？')
        box.setInformativeText('默认全部数据。仅可见行以文件最后保存的状态为准，也排除手动隐藏的行。\n若刚调整过筛选，请取消，先保存文件再重新读取。')
        visible=box.addButton('仅可见行',QMessageBox.ActionRole)
        all_rows=box.addButton('全部数据',QMessageBox.AcceptRole)
        cancel=box.addButton('取消',QMessageBox.RejectRole)
        box.setDefaultButton(all_rows);box.setEscapeButton(cancel);box.exec()
        if box.clickedButton()==visible:return True
        if box.clickedButton()==all_rows:return False
        return None

    def show_preview(self,preview):
        self.preview=preview;self.confirmed_preview=None;self.result=None;self.category_table.blockSignals(True)
        self.category_table.setRowCount(len(preview.groups))
        for row,g in enumerate(preview.groups):
            check=QTableWidgetItem();check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable);check.setCheckState(Qt.Checked);check.setData(Qt.UserRole,g.id)
            self.category_table.setItem(row,0,check)
            for col,text in enumerate((g.label,str(len(g.source_rows)),preview.names[g.id]),1):
                item=QTableWidgetItem(text);item.setToolTip(text);self.category_table.setItem(row,col,item)
        self.category_table.blockSignals(False);self.steps.setCurrentIndex(2);self.update_step();self.update_summary()
        self.status_label.setText('\n'.join(preview.warnings) or '预览完成，请核对类别和记录数。')

    def set_all(self,checked):
        self.category_table.blockSignals(True)
        for row in range(self.category_table.rowCount()):self.category_table.item(row,0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.category_table.blockSignals(False);self.selection_changed()

    def selection_changed(self,*_):
        if self.preview is None:return
        ids=tuple(self.category_table.item(row,0).data(Qt.UserRole) for row in range(self.category_table.rowCount())
                  if self.category_table.item(row,0).checkState()==Qt.Checked)
        self.preview=select_groups(self.preview,ids);self.confirmed_preview=None;self.update_summary()

    def update_summary(self):
        p=self.preview
        if p is None:return
        c=p.counts;mode='仅可见行' if p.options.visible_only else '全部数据'
        files=len(p.selected_ids) if p.options.output_mode=='files' else int(bool(p.selected_ids))
        for label,text in zip(self.metric_labels,(f'{len(p.selected_ids)} 类  已选择',f'{c.exported} 条  将导出',f'{files} 个  结果文件')):
            label.setText(text)
        self.summary_label.setText(f'{mode} · 共 {len(p.groups)} 类，已选 {len(p.selected_ids)} 类，未选 {len(p.groups)-len(p.selected_ids)} 类\n'
                                  f'导出 {c.exported} 条 · 未选 {c.unselected} 条 · 隐藏排除 {c.hidden} 条 · 空白跳过 {c.blank} 条\n'
                                  f'保存位置：{p.result_folder}')
        self.confirm_button.setEnabled(bool(p.selected_ids) and self.result is None and not self.busy)

    def confirmation_text(self):
        p=self.preview;o=p.options;c=p.counts
        files=len(p.selected_ids) if o.output_mode=='files' else 1
        return (f'【处理范围】\n源文件：{o.source}\n工作表：{o.sheet}\n区域：{o.area or "整个工作表"} · 表头 {o.header_rows} 行\n'
                f'分类列：{", ".join(str(v) for v in o.key_columns)} · 忽略首尾空格：{"是" if o.trim_keys else "否"}\n'
                f'\n【生成结果】\n{self.summary_label.text()}\n预计生成 {files} 个文件、{len(p.selected_ids)} 个分类工作表。\n\n'
                '【公式提醒】\n公式将转换为文件中已保存的计算结果，拆分后不会随数据变化自动计算。'
                '请先在 Excel 中完成计算并保存。未选类别不会导出，原文件保持不变。')

    def ask_confirmation(self):
        box=QMessageBox(self);box.setWindowTitle('确认分类拆分');box.setText('请核对本次拆分范围和结果')
        box.setInformativeText(self.confirmation_text());box.setTextFormat(Qt.PlainText)
        back=box.addButton('返回调整',QMessageBox.RejectRole);yes=box.addButton('确认拆分',QMessageBox.AcceptRole)
        box.setDefaultButton(back);box.setEscapeButton(back);box.exec()
        return box.clickedButton()==yes

    def confirm_export(self):
        if self.busy or self.preview is None or not self.preview.selected_ids or self.result is not None:return
        if not self.ask_confirmation():return
        self.confirmed_preview=self.preview;confirmed=self.confirmed_preview
        self.status_label.setText('正在生成并核对结果…')
        def done(result):
            self.result=result;self.status_label.setText(f'拆分完成：{result.exported_rows} 条记录，{len(result.output_files)} 个文件。\n{result.output_folder}')
            self.confirm_button.setEnabled(False);self.open_button.show()
        self.run_job(lambda progress:self.export_fn(confirmed,progress),done)

    def go_back(self):
        if self.busy:return
        self.steps.setCurrentIndex(max(0,self.steps.currentIndex()-1));self.update_step()

    def update_step(self):
        index=self.steps.currentIndex()
        for i,badge in enumerate(self.step_badges):
            badge.setProperty('active',i==index);badge.style().unpolish(badge);badge.style().polish(badge)
        self.step_label.setText(f'第 {index+1} 步 / 3　'+('选择数据','设置分类','预览并执行')[index])
        self.back_button.setVisible(index>0);self.next_button.setVisible(index<2);self.confirm_button.setVisible(index==2)
        self.next_button.setText('下一步：设置分类' if index==0 else '生成分类预览')
        self.confirm_button.setEnabled(index==2 and self.preview is not None and bool(self.preview.selected_ids) and self.result is None)

    def open_result(self):
        if self.result and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.output_folder))):
            self.status_label.setText(f'无法自动打开，请手动访问：{self.result.output_folder}')

    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
