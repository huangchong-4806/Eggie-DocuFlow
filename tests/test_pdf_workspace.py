import tempfile
import multiprocessing
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pdf_workspace as workspace

from pdf_workspace import (
    NumberOptions,
    PageScope,
    RedactionMark,
    WorkspaceState,
    marks_with_state,
    number_label,
    pending_count,
    resolve_pages,
)


class WorkspaceRulesTests(unittest.TestCase):
    def test_page_scope_deduplicates_and_skips_current_first_page(self):
        self.assertEqual(resolve_pages(PageScope("1-3,2,5", True), 5), (1, 2, 4))
        self.assertEqual(resolve_pages(PageScope(), 3), (0, 1, 2))
        self.assertEqual(resolve_pages(PageScope("3, 1"), 3), (0, 2))

    def test_invalid_or_empty_scope_is_rejected_instead_of_silently_skipped(self):
        for ranges in ("0", "3-1", "1,6", "x", "1,", "1.5", "1--3"):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                resolve_pages(PageScope(ranges), 5)
        with self.assertRaises(ValueError):
            resolve_pages(PageScope(skip_first=True), 1)

    def test_all_number_styles_use_start_and_real_document_total(self):
        expected = {
            "plain": "4", "dash": "— 4 —", "chinese": "第 4 页",
            "fraction": "4 / 8", "chinese_total": "第 4 页，共 8 页",
        }
        for style, label in expected.items():
            with self.subTest(style=style):
                self.assertEqual(number_label(NumberOptions(style=style, start=3), 1, 8), label)
        self.assertEqual(number_label(NumberOptions(start=0), 0, 2), "0")
        with self.assertRaises(ValueError):
            number_label(NumberOptions(start=-1), 0, 2)
        with self.assertRaises(ValueError):
            number_label(NumberOptions(style="invalid"), 0, 2)

    def test_applied_marks_can_be_followed_by_new_marks_and_restored_without_a_cap(self):
        pending = [RedactionMark(str(i), "page-a", ((1, 1, 2, 2),)) for i in range(10001)]
        state = WorkspaceState(marks=pending)
        self.assertEqual(pending_count(state), 10001)
        state.marks = marks_with_state(state.marks, True)
        self.assertFalse(pending[0].applied)
        state.marks.append(RedactionMark("new", "page-b", ((3, 3, 4, 4),)))
        self.assertEqual(pending_count(state), 1)
        state.marks = marks_with_state(state.marks, False)
        self.assertEqual(pending_count(state), 10002)
        self.assertEqual(state.marks[-1].page_id, "page-b")


class WorkspaceEngineTests(unittest.TestCase):
    def setUp(self):
        import pymupdf

        self.pdf = pymupdf
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page(width=300, height=400)
            page.insert_text((30, 60), "SECRET-123 KEEP-456", fontsize=12)
            page.insert_text((30, 100), "UNCHANGED", fontsize=12)
            doc.save(str(self.source))
        self.engine = workspace.PdfWorkspaceEngine()
        self.addCleanup(self.engine.close)
        self.pages = self.engine.open_pdf(str(self.source))
        self.state = WorkspaceState(pages=list(self.pages))

    def test_render_preserves_source_text_and_uses_an_immutable_snapshot(self):
        preview = self.engine.render_page(self.state, self.pages[0].page_id, 600)
        self.assertTrue(preview["png"].startswith(b"\x89PNG"))
        self.assertEqual((preview["width_pt"], preview["height_pt"]), (300, 400))
        self.assertIn("KEEP-456", "".join(char["text"] for char in preview["chars"]))

        self.source.write_bytes(b"source externally replaced")
        repeated = self.engine.render_page(self.state, self.pages[0].page_id, 600)
        self.assertEqual(repeated["png"], preview["png"])

    def test_unsupported_watermark_characters_block_preview_and_export(self):
        for text in ("内部资料🔒", "𠮷野家"):
            state = replace(self.state, watermark=workspace.WatermarkOptions(kind="text", text=text))
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "字符"):
                    self.engine.render_page(state, self.pages[0].page_id)
                with self.assertRaisesRegex(ValueError, "字符"):
                    self.engine.export_pdf(state, str(self.root / "missing-glyph.pdf"))
                self.assertFalse((self.root / "missing-glyph.pdf").exists())

    def test_release_resources_closes_only_discarded_snapshots(self):
        discarded = self.engine._sources[self.pages[0].source_id]
        retained = self.engine.open_pdf(str(self.source))[0]
        image_path = self.root / "stamp.png"
        pixmap = self.pdf.Pixmap(self.pdf.csRGB, self.pdf.IRect(0, 0, 20, 20), False)
        pixmap.clear_with(100)
        pixmap.save(str(image_path))
        image_id = self.engine.open_watermark_image(str(image_path))
        self.engine.release_resources((self.pages[0].source_id,), (image_id,))
        self.assertTrue(discarded.is_closed)
        self.assertNotIn(image_id, self.engine._images)
        state = WorkspaceState(pages=[retained])
        preview = self.engine.render_page(state, retained.page_id)
        self.assertIn("KEEP-456", "".join(char["text"] for char in preview["chars"]))
        self.engine.release_resources((self.pages[0].source_id,), (image_id,))

    def test_cleanup_failure_after_publish_keeps_success_and_all_warnings(self):
        target = self.root / "cleanup.pdf"
        unlink = Path.unlink
        def deny_cleanup(path, *args, **kwargs):
            if path.name.startswith(".cleanup-"):
                raise PermissionError("synthetic cleanup refusal")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", deny_cleanup), patch("pdf_toolbox.write_log", side_effect=OSError("synthetic log failure")):
            result = self.engine.export_pdf(self.state, str(target))
        self.assertEqual(Path(result.output_file), target.resolve())
        self.assertEqual(len(result.failures), 2)
        self.assertIn("临时文件", "".join(result.failures))
        self.assertIn("记录", "".join(result.failures))
        with self.pdf.open(result.output_file) as doc:
            self.assertIn("KEEP-456", doc[0].get_text())

    def test_failed_verification_and_cleanup_never_report_success(self):
        target = self.root / "failed.pdf"
        unlink = Path.unlink
        def deny_cleanup(path, *args, **kwargs):
            if path.name.startswith(".failed-"):
                raise PermissionError("synthetic cleanup refusal")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", deny_cleanup), patch.object(self.engine, "_verify_output", side_effect=ValueError("verification failed")):
            with self.assertRaisesRegex(ValueError, "临时文件"):
                self.engine.export_pdf(self.state, str(target))
        self.assertFalse(target.exists())

    def test_cropped_rotated_pages_roundtrip_selection_coordinates(self):
        path = self.root / "cropped.pdf"
        with self.pdf.open(str(self.source)) as doc:
            doc[0].set_cropbox(self.pdf.Rect(10, 20, 290, 380))
            doc[0].set_rotation(90)
            doc.save(str(path))
        page_ref = self.engine.open_pdf(str(path))[0]
        for rotation, size in ((0, (360, 280)), (90, (280, 360)), (180, (360, 280)), (270, (280, 360))):
            with self.subTest(rotation=rotation):
                state = WorkspaceState(pages=[replace(page_ref, rotation=rotation)])
                preview = self.engine.render_page(state, page_ref.page_id, 400)
                self.assertEqual((preview["width_pt"], preview["height_pt"]), size)
                matrix = self.pdf.Matrix(*preview["source_to_view"])
                point = self.pdf.Point(35, 40)
                result = point * matrix * ~matrix
                self.assertLess(abs(result.x - point.x) + abs(result.y - point.y), 0.01)
                self.assertIn("UNCHANGED", "".join(char["text"] for char in preview["chars"]))

    def test_explicit_reopen_reads_new_file_without_changing_previous_snapshot(self):
        with self.pdf.open() as doc:
            doc.new_page().insert_text((30, 50), "NEW CONTENT")
            doc.save(str(self.source))
        new_pages = self.engine.open_pdf(str(self.source))
        new_state = WorkspaceState(pages=list(new_pages))
        fresh = self.engine.render_page(new_state, new_pages[0].page_id)
        old = self.engine.render_page(self.state, self.pages[0].page_id)
        self.assertIn("NEW CONTENT", "".join(c["text"] for c in fresh["chars"]))
        self.assertIn("KEEP-456", "".join(c["text"] for c in old["chars"]))

    def test_invalid_pdf_does_not_replace_an_open_document(self):
        broken = self.root / "broken.pdf"
        broken.write_bytes(b"not a PDF")
        with self.assertRaises(ValueError):
            self.engine.open_pdf(str(broken))
        preview = self.engine.render_page(self.state, self.pages[0].page_id)
        self.assertIn("KEEP-456", "".join(char["text"] for char in preview["chars"]))

    def test_password_and_dynamic_form_safety(self):
        encrypted = self.root / "encrypted.pdf"
        with self.pdf.open(str(self.source)) as doc:
            doc.save(str(encrypted), encryption=self.pdf.PDF_ENCRYPT_AES_256,
                     owner_pw="synthetic-owner", user_pw="synthetic-reader")
        with self.assertRaisesRegex(ValueError, "加密"):
            self.engine.open_pdf(str(encrypted), password="wrong")
        self.assertEqual(len(self.engine.open_pdf(str(encrypted), password="synthetic-reader")), 1)
        dynamic = self.root / "dynamic.pdf"
        with self.pdf.open(str(self.source)) as doc:
            doc.xref_set_key(doc.pdf_catalog(), "AcroForm", "<< /XFA (synthetic) >>")
            doc.save(str(dynamic))
        pages = self.engine.open_pdf(str(dynamic))
        state = WorkspaceState(pages=list(pages), marks=[RedactionMark(
            "m", pages[0].page_id, ((30, 40, 70, 62),), applied=True)])
        with self.assertRaisesRegex(ValueError, "动态表单"):
            self.engine.export_pdf(state, str(self.root / "not-published.pdf"))
        self.assertFalse((self.root / "not-published.pdf").exists())

    def test_unknown_page_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.render_page(self.state, "unknown")

    def mark_secret(self, applied=True):
        with self.pdf.open(str(self.source)) as doc:
            rect = tuple(doc[0].search_for("SECRET-123")[0])
        self.state.marks = [RedactionMark("secret", self.pages[0].page_id, (rect,), "text", applied)]

    def test_export_physically_removes_marked_text_and_keeps_other_text(self):
        self.mark_secret()
        before = self.source.read_bytes()
        result = self.engine.export_pdf(self.state, str(self.root / "redacted.pdf"))
        with self.pdf.open(result.output_file) as doc:
            self.assertNotIn("SECRET-123", doc[0].get_text())
            self.assertIn("KEEP-456", doc[0].get_text())
            self.assertIn("UNCHANGED", doc[0].get_text())
            self.assertEqual(list(doc[0].annots() or ()), [])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertNotIn("SECRET-123", Path(result.log_file).read_text(encoding="utf-8"))
        self.state.marks = marks_with_state(self.state.marks, False)
        preview = self.engine.render_page(self.state, self.pages[0].page_id)
        self.assertIn("SECRET-123", "".join(c["text"] for c in preview["chars"]))

    def test_pending_marks_block_export_even_on_other_pages(self):
        self.mark_secret(applied=False)
        with self.assertRaisesRegex(ValueError, "待应用"):
            self.engine.export_pdf(self.state, str(self.root / "pending.pdf"))
        self.assertFalse((self.root / "pending.pdf").exists())

    def test_apply_validates_without_mutating_original_marks(self):
        self.mark_secret(applied=False)
        self.engine.validate_apply(self.state)
        self.assertEqual(pending_count(self.state), 1)
        self.state.marks = marks_with_state(self.state.marks, True)
        preview = self.engine.render_page(self.state, self.pages[0].page_id)
        self.assertNotIn("SECRET-123", "".join(c["text"] for c in preview["chars"]))

    def test_apply_and_export_report_real_page_progress(self):
        self.mark_secret()
        progress = []
        self.engine.validate_apply(self.state, progress=progress.append)
        self.assertTrue(any("1 / 1" in text for text in progress))
        progress.clear()
        self.engine.export_pdf(self.state, str(self.root / "progress.pdf"), progress=progress.append)
        self.assertTrue(any("1 / 1" in text for text in progress))
        self.assertTrue(any("核验" in text for text in progress))

    def test_invalid_rectangle_and_missing_page_cannot_bypass_export(self):
        for rect, page_id in (((-1, 2, 10, 10), self.pages[0].page_id),
                              ((1, 1, float("nan"), 10), self.pages[0].page_id),
                              ((1, 1, 10, 10), "deleted-page")):
            with self.subTest(rect=rect, page_id=page_id):
                self.state.marks = [RedactionMark("invalid", page_id, (rect,), applied=True)]
                with self.assertRaises(ValueError):
                    self.engine.export_pdf(self.state, str(self.root / "invalid.pdf"))
        self.assertFalse((self.root / "invalid.pdf").exists())

    def test_verification_failure_does_not_publish_or_leave_temporary_file(self):
        self.mark_secret()
        before = set(self.root.iterdir())
        with patch.object(self.engine, "_verify_output", side_effect=ValueError("verification failed")):
            with self.assertRaises(ValueError):
                self.engine.export_pdf(self.state, str(self.root / "failed.pdf"))
        self.assertEqual(set(self.root.iterdir()), before)

    def test_saved_page_visual_change_is_rejected_even_when_text_is_unchanged(self):
        self.mark_secret()
        verify = self.engine._verify_output
        def change_visual_then_verify(path, expected, secure):
            with self.pdf.open(str(path)) as document:
                document[0].draw_rect((210, 220, 240, 260), fill=(0, 0, 0))
                document.saveIncr()
            return verify(path, expected, secure)
        before = set(self.root.iterdir())
        with patch.object(self.engine, "_verify_output", side_effect=change_visual_then_verify):
            with self.assertRaisesRegex(ValueError, "外观"):
                self.engine.export_pdf(self.state, str(self.root / "changed.pdf"))
        self.assertEqual(set(self.root.iterdir()), before)

    def test_same_name_does_not_overwrite_and_log_failure_keeps_valid_pdf(self):
        self.mark_secret()
        target = self.root / "out.pdf"
        target.write_bytes(b"existing")
        with patch("pdf_toolbox.write_log", side_effect=OSError("disk full")):
            result = self.engine.export_pdf(self.state, str(target))
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertEqual(Path(result.output_file).name, "out_1.pdf")
        self.assertTrue(result.failures)
        with self.pdf.open(result.output_file) as doc:
            self.assertNotIn("SECRET-123", doc[0].get_text())

    def test_attachments_and_annotation_notes_require_cleanup_confirmation(self):
        path = self.root / "notes.pdf"
        with self.pdf.open(str(self.source)) as doc:
            doc.embfile_add("private.txt", b"SECRET-ATTACHMENT")
            doc[0].add_text_annot((180, 160), "SECRET-NOTE")
            doc.set_metadata({"title": "SECRET-TITLE"})
            doc.save(str(path))
        page = self.engine.open_pdf(str(path))[0]
        self.state = WorkspaceState(pages=[page], marks=[RedactionMark("area", page.page_id, ((20, 45, 110, 65),), applied=True)])
        inspection = self.engine.inspect_document(self.state)
        self.assertEqual(inspection["attachments"], 1)
        self.assertEqual(inspection["annotations"], 1)
        with self.assertRaisesRegex(ValueError, "确认"):
            self.engine.export_pdf(self.state, str(self.root / "without-consent.pdf"))
        result = self.engine.export_pdf(self.state, str(self.root / "clean.pdf"), allow_cleanup=True)
        with self.pdf.open(result.output_file) as doc:
            self.assertEqual(doc.embfile_count(), 0)
            self.assertFalse(doc.metadata.get("title"))
            objects = "".join(doc.xref_object(i) for i in range(1, doc.xref_length()))
            self.assertNotIn("SECRET-NOTE", objects)
            self.assertNotIn("SECRET-ATTACHMENT", objects)

    def test_optional_hidden_layers_are_refused_for_redaction(self):
        path = self.root / "layers.pdf"
        with self.pdf.open(str(self.source)) as doc:
            ocg = doc.add_ocg("hidden", on=False)
            doc[0].insert_text((30, 60), "HIDDEN SECRET", oc=ocg)
            doc.save(str(path))
        page = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[page], marks=[RedactionMark("m", page.page_id, ((20, 40, 100, 70),), applied=True)])
        self.assertTrue(self.engine.inspect_document(state)["blocking_reasons"])
        with self.assertRaises(ValueError):
            self.engine.export_pdf(state, str(self.root / "unsafe.pdf"), allow_cleanup=True)

    def test_image_redaction_replaces_extractable_pixels_not_only_the_overlay(self):
        path = self.root / "image.pdf"
        pixmap = self.pdf.Pixmap(self.pdf.csRGB, self.pdf.IRect(0, 0, 100, 100), False)
        pixmap.clear_with(80)
        with self.pdf.open(str(self.source)) as doc:
            doc[0].insert_image(self.pdf.Rect(20, 120, 220, 320), pixmap=pixmap)
            doc.save(str(path))
        page = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[page], marks=[RedactionMark("image", page.page_id, ((50, 150, 90, 190),), applied=True)])
        result = self.engine.export_pdf(state, str(self.root / "safe-image.pdf"))
        with self.pdf.open(result.output_file) as doc:
            images = doc[0].get_images()
            self.assertEqual(len(images), 1)
            extracted = self.pdf.Pixmap(doc, images[0][0])
            self.assertEqual(extracted.pixel(25, 25), (255, 255, 255))
            self.assertEqual(extracted.pixel(70, 70), (80, 80, 80))
            rendered = doc[0].get_pixmap()
            self.assertEqual(rendered.pixel(70, 170), (0, 0, 0))
            self.assertIn("KEEP-456", doc[0].get_text())

    def test_shared_image_original_cannot_be_leaked_from_another_page(self):
        path = self.root / "shared.pdf"
        pixmap = self.pdf.Pixmap(self.pdf.csRGB, self.pdf.IRect(0, 0, 100, 100), False)
        pixmap.clear_with(80)
        with self.pdf.open() as doc:
            first = doc.new_page(width=300, height=400)
            xref = first.insert_image(self.pdf.Rect(20, 120, 220, 320), pixmap=pixmap)
            second = doc.new_page(width=300, height=400)
            second.insert_image(self.pdf.Rect(20, 120, 220, 320), xref=xref)
            doc.save(str(path))
        pages = list(self.engine.open_pdf(str(path)))
        state = WorkspaceState(pages=pages, marks=[RedactionMark("image", pages[0].page_id, ((50, 150, 90, 190),), applied=True)])
        with self.assertRaisesRegex(ValueError, "复用"):
            self.engine.export_pdf(state, str(self.root / "unsafe-shared.pdf"))
        self.assertFalse((self.root / "unsafe-shared.pdf").exists())

    def test_hidden_ocr_outside_redaction_survives_and_crossing_lines_are_removed(self):
        path = self.root / "ocr.pdf"
        with self.pdf.open(str(self.source)) as doc:
            page = doc[0]
            page.insert_text((30, 170), "OCR SECRET OCR KEEP", render_mode=3)
            page.draw_line((10, 55), (290, 55), color=(1, 0, 0))
            doc.save(str(path))
        ref = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id,
            ((20, 42, 107, 65), (20, 150, 98, 180)), applied=True)])
        result = self.engine.export_pdf(state, str(self.root / "ocr-clean.pdf"))
        with self.pdf.open(result.output_file) as doc:
            self.assertIn("OCR KEEP", doc[0].get_text())
            self.assertNotIn("SECRET", doc[0].get_text())
            self.assertFalse(any(item["type"] == "s" for item in doc[0].get_drawings()))

    def test_inline_actualtext_cannot_hide_a_second_copy(self):
        path = self.root / "alternate.pdf"
        with self.pdf.open(str(self.source)) as doc:
            xref = doc[0].get_contents()[0]
            original = doc.xref_stream(xref)
            doc.update_stream(xref, b"/Span << /ActualText (HIDDEN ORIGINAL) >> BDC\n" + original + b"\nEMC")
            doc.save(str(path))
        ref = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, ((20, 40, 105, 70),), applied=True)])
        with self.assertRaises(ValueError):
            self.engine.export_pdf(state, str(self.root / "alternate-clean.pdf"))

    def test_escaped_pdf_names_cannot_hide_alternate_text(self):
        for key in (b"/A#6Ct", b"/#41ctualText"):
            path = self.root / (key.hex() + ".pdf")
            with self.pdf.open(str(self.source)) as doc:
                xref = doc[0].get_contents()[0]
                doc.update_stream(xref, b"/Span << " + key + b" (HIDDEN ORIGINAL) >> BDC\n" + doc.xref_stream(xref) + b"\nEMC")
                doc.save(str(path))
            ref = self.engine.open_pdf(str(path))[0]
            state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, ((30, 47, 100, 65),), applied=True)])
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.engine.export_pdf(state, str(self.root / "escaped.pdf"))

    def test_nested_named_properties_cannot_retain_sensitive_alternate_text(self):
        path = self.root / "named-properties.pdf"
        with self.pdf.open(str(self.source)) as doc:
            page = doc[0]
            resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
            doc.xref_set_key(resources, "Properties", "<< /MC1 << /Alt (SECRET-123) >> >>")
            xref = page.get_contents()[0]
            doc.update_stream(xref, b"/Span /MC1 BDC\n" + doc.xref_stream(xref) + b"\nEMC")
            doc.save(str(path))
        ref = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, ((20, 40, 103, 70),), applied=True)])
        self.assertTrue(self.engine.inspect_document(state)["blocking_reasons"])
        with self.assertRaises(ValueError):
            self.engine.export_pdf(state, str(self.root / "named-clean.pdf"))

    def test_crop_and_rotation_redaction_keeps_the_unmarked_text(self):
        for rotation in (0, 90, 180, 270):
            path = self.root / f"crop-{rotation}.pdf"
            with self.pdf.open(str(self.source)) as doc:
                doc[0].set_cropbox(self.pdf.Rect(10, 20, 290, 380))
                doc[0].set_rotation(rotation)
                rect = tuple(doc[0].search_for("SECRET-123")[0])
                doc.save(str(path))
            ref = self.engine.open_pdf(str(path))[0]
            state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, (rect,), applied=True)])
            result = self.engine.export_pdf(state, str(self.root / f"crop-safe-{rotation}.pdf"))
            with self.pdf.open(result.output_file) as doc:
                self.assertNotIn("SECRET-123", doc[0].get_text())
                self.assertIn("KEEP-456", doc[0].get_text())

    def test_cancel_before_publish_keeps_original_and_leaves_no_partial_output(self):
        self.mark_secret()
        before = set(self.root.iterdir())
        with self.assertRaises(InterruptedError):
            self.engine.export_pdf(self.state, str(self.root / "cancelled.pdf"), cancelled=lambda: True)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_supplied_temporary_path_cannot_overwrite_an_existing_file(self):
        target = self.root / "result.pdf"
        protected = self.root / ".result-existing.pdf"
        protected.write_bytes(b"keep this existing file")
        with self.assertRaisesRegex(ValueError, "临时输出路径"):
            self.engine.export_pdf(self.state, str(target), temporary_path=str(protected))
        self.assertEqual(protected.read_bytes(), b"keep this existing file")
        self.assertFalse(target.exists())

    def test_spawn_worker_owns_engine_reports_errors_and_closes(self):
        context = multiprocessing.get_context("spawn")
        requests, responses = context.Queue(), context.Queue()
        process = context.Process(target=workspace.run_pdf_workspace_worker, args=(requests, responses))
        process.start()
        try:
            requests.put((1, 7, "open", {"path": str(self.source)}))
            request_id, revision, kind, pages = responses.get(timeout=15)
            self.assertEqual((request_id, revision, kind), (1, 7, "completed"))
            requests.put((2, 8, "render", {"state": WorkspaceState(pages=list(pages)), "page_id": pages[0].page_id}))
            response = responses.get(timeout=15)
            self.assertEqual(response[:3], (2, 8, "completed"))
            self.assertTrue(response[3]["png"].startswith(b"\x89PNG"))
            requests.put((3, 8, "__getattribute__", {}))
            self.assertEqual(responses.get(timeout=15)[:3], (3, 8, "failed"))
            requests.put((4, 8, "release", {"source_ids": (pages[0].source_id,)}))
            self.assertEqual(responses.get(timeout=15)[:3], (4, 8, "completed"))
            requests.put((5, 8, "render", {"state": WorkspaceState(pages=list(pages)), "page_id": pages[0].page_id}))
            self.assertEqual(responses.get(timeout=15)[:3], (5, 8, "failed"))
            requests.put((6, 8, "close", {}))
            self.assertEqual(responses.get(timeout=15)[:3], (6, 8, "completed"))
            process.join(5)
            self.assertFalse(process.is_alive())
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)
            requests.close()
            responses.close()

    def test_watermarks_and_numbers_share_the_preview_and_export_path(self):
        pages = list(self.pages) + [replace(self.pages[0], page_id="p2")]
        self.state = WorkspaceState(pages=pages, watermark=workspace.WatermarkOptions(
            kind="text", text="本地水印", angle=0, tiled=True, scope=PageScope(skip_first=True)),
            numbers=NumberOptions(enabled=True, style="chinese_total", start=0))
        preview = self.engine.render_page(self.state, "p2", 400)
        result = self.engine.export_pdf(self.state, str(self.root / "decorated.pdf"))
        with self.pdf.open(result.output_file) as doc:
            self.assertNotIn("本地水印", doc[0].get_text())
            self.assertIn("本地水印", doc[1].get_text())
            self.assertIn("第 0 页，共 2 页", doc[0].get_text())
            self.assertIn("第 1 页，共 2 页", doc[1].get_text())
            self.assertEqual(preview["png"], doc[1].get_pixmap().tobytes("png"))

    def test_image_watermark_snapshot_and_all_number_positions(self):
        path = self.root / "watermark.png"
        pixmap = self.pdf.Pixmap(self.pdf.csRGB, self.pdf.IRect(0, 0, 30, 20), False)
        pixmap.clear_with(200)
        pixmap.save(str(path))
        image_id = self.engine.open_watermark_image(str(path))
        path.write_bytes(b"externally replaced")
        for position in ("top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right"):
            self.state.watermark = workspace.WatermarkOptions(kind="image", image_id=image_id, tiled=True)
            self.state.numbers = NumberOptions(enabled=True, position=position)
            result = self.engine.export_pdf(self.state, str(self.root / f"{position}.pdf"))
            with self.pdf.open(result.output_file) as doc:
                self.assertTrue(doc[0].get_images())
                self.assertIn("1", doc[0].get_text())

    def test_invalid_watermark_settings_cannot_silently_export_without_edits(self):
        for options in (workspace.WatermarkOptions(kind="text", text=""),
                        workspace.WatermarkOptions(kind="text", opacity=float("nan")),
                        workspace.WatermarkOptions(kind="image", image_id="missing"),
                        workspace.WatermarkOptions(kind="text", size=-10)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.engine.export_pdf(replace(self.state, watermark=options), str(self.root / "invalid.pdf"))

    def test_watermark_layout_generates_positive_boxes(self):
        boxes = workspace.watermark_boxes(300, 400, 60, 30, 20, True)
        self.assertGreater(len(boxes), 1)
        self.assertTrue(all(x1 > x0 and y1 > y0 for x0, y0, x1, y1 in boxes))

    def test_independent_reader_and_renderer_verify_chinese_redaction(self):
        from pypdf import PdfReader
        import pypdfium2

        path = self.root / "chinese.pdf"
        with self.pdf.open() as doc:
            page = doc.new_page(width=300, height=400)
            page.insert_font(fontname="TestCJK", fontbuffer=self.pdf.Font("cjk").buffer)
            page.insert_text((30, 60), "机密内容", fontname="TestCJK", fontsize=14)
            page.insert_text((30, 110), "保留文字可以复制", fontname="TestCJK", fontsize=14)
            rect = tuple(page.search_for("机密内容")[0])
            doc.save(str(path))
        ref = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, (rect,), "text", True)])
        result = self.engine.export_pdf(state, str(self.root / "chinese-safe.pdf"))
        text = PdfReader(result.output_file).pages[0].extract_text()
        self.assertNotIn("机密内容", text)
        self.assertIn("保留文字可以复制", text)
        with pypdfium2.PdfDocument(result.output_file) as document:
            page = document[0]
            bitmap = page.render(scale=1)
            image = bitmap.to_pil()
            self.assertEqual(image.getpixel((50, 55))[:3], (0, 0, 0))
            bitmap.close()
            page.close()

    def test_forms_scripts_and_incremental_history_are_not_carried_to_redacted_output(self):
        path = self.root / "form.pdf"
        with self.pdf.open(str(self.source)) as doc:
            widget = self.pdf.Widget()
            widget.field_name = "private"
            widget.field_type = self.pdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = self.pdf.Rect(30, 200, 200, 230)
            widget.field_value = "FORMSECRET"
            doc[0].add_widget(widget)
            doc.xref_set_key(doc[0].xref, "AA", "<< /O << /S /JavaScript /JS (SCRIPTSECRET) >> >>")
            doc.set_metadata({"title": "HISTORYSECRET"})
            doc.save(str(path))
        with self.pdf.open(str(path)) as doc:
            doc.set_metadata({"title": "updated"})
            doc.saveIncr()
        before = path.read_bytes()
        ref = self.engine.open_pdf(str(path))[0]
        state = WorkspaceState(pages=[ref], marks=[RedactionMark("m", ref.page_id, ((20, 190, 210, 240),), applied=True)])
        result = self.engine.export_pdf(state, str(self.root / "form-safe.pdf"), allow_cleanup=True)
        with self.pdf.open(result.output_file) as doc:
            data = b"".join(doc.xref_object(i).encode() + (doc.xref_stream(i) if doc.xref_is_stream(i) else b"") for i in range(1, doc.xref_length()))
            for secret in (b"FORMSECRET", b"HISTORYSECRET", b"SCRIPTSECRET"):
                self.assertNotIn(secret, data)
            self.assertIn("KEEP-456", doc[0].get_text())
            self.assertFalse(list(doc[0].widgets() or ()))
        self.assertEqual(path.read_bytes(), before)

    def test_number_position_is_correct_in_rotated_view_coordinates(self):
        for rotation in (0, 90, 180, 270):
            ref = replace(self.pages[0], rotation=rotation)
            state = WorkspaceState(pages=[ref], numbers=NumberOptions(enabled=True, start=987, position="top_left"))
            result = self.engine.export_pdf(state, str(self.root / f"number-{rotation}.pdf"))
            with self.pdf.open(result.output_file) as doc:
                page = doc[0]
                rect = page.search_for("987")[0] * page.rotation_matrix
                self.assertLess(rect.x0, 35)
                self.assertLess(rect.y0, 35)
                self.assertGreater(rect.width, rect.height)


if __name__ == "__main__":
    unittest.main()
