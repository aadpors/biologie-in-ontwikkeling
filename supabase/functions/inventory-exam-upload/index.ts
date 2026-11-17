import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";
import { unzipSync } from "npm:fflate@0.8.2";
import * as pdfjs from "npm:pdfjs-dist@4.10.38/legacy/build/pdf.mjs";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const BUCKET = "exam-inbox";
const MAX_ENTRIES = 150;
const MAX_UNZIPPED = 1024 * 1024 * 1024;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, apikey, content-type", "access-control-allow-methods": "POST, OPTIONS" } });

function filenameMeta(name: string) {
  const lower = name.split("/").pop()!.toLowerCase();
  const m = lower.match(/^(ha|vw)[-_]?1018[-_]a[-_]?(\d{2})[-_]?(\d)[-_]?([a-z0-9-]+)\.pdf$/i);
  const year = m ? 2000 + Number(m[2]) : null;
  const level = m ? (m[1] === "ha" ? "havo" : "vwo") : null;
  const period = m ? Number(m[3]) : null;
  let documentType = "onbekend";
  if (/(^|[-_])c(?:[-_]|\.|$)/i.test(lower)) documentType = "correctievoorschrift";
  else if (/(^|[-_])o(?:[-_]|\.|$)/i.test(lower)) documentType = "opgaven";
  else if (/(^|[-_])u(?:[-_]|\.|$)/i.test(lower)) documentType = "uitwerkbijlage";
  else if (/aanvulling|addendum|a1_?0/i.test(lower)) documentType = "aanvulling_correctievoorschrift";
  return { level, year, period, documentType };
}
async function inspectPdf(bytes: Uint8Array, name: string) {
  const task = pdfjs.getDocument({ data: bytes, useSystemFonts: true, isEvalSupported: false, disableFontFace: true, verbosity: 0 });
  const pdf = await task.promise;
  const pages = [];
  let totalChars = 0;
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const content = await page.getTextContent();
    const items = (content.items || []).filter((x: any) => typeof x.str === "string");
    const text = items.map((x: any) => x.str).join(" ").replace(/\s+/g, " ").trim();
    totalChars += text.length;
    const viewport = page.getViewport({ scale: 1 });
    pages.push({ page: n, width: Math.round(viewport.width), height: Math.round(viewport.height), text, textCharacters: text.length, hasExtractableText: text.length >= 20 });
    page.cleanup();
  }
  await pdf.destroy();
  return { filename: name, ...filenameMeta(name), pageCount: pages.length, totalTextCharacters: totalChars, pages };
}
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return json({ ok: true });
  if (req.method !== "POST") return json({ error: "Gebruik POST." }, 405);
  let jobId: string | null = null;
  try {
    const authHeader = req.headers.get("Authorization") || "";
    if (!authHeader.startsWith("Bearer ")) return json({ error: "Aanmelden vereist." }, 401);
    const token = authHeader.slice(7);
    const authClient = createClient(SUPABASE_URL, ANON_KEY, { global: { headers: { Authorization: "Bearer " + token } } });
    const { data: userData, error: authError } = await authClient.auth.getUser(token);
    if (authError || !userData.user || userData.user.is_anonymous !== true) return json({ error: "Alleen de tijdelijke anonieme beheerder mag verwerken." }, 403);
    const body = await req.json();
    jobId = body.job_id;
    if (typeof jobId !== "string") return json({ error: "job_id ontbreekt." }, 400);
    const admin = createClient(SUPABASE_URL, SERVICE_KEY);
    const { data: job, error: jobError } = await admin.from("exam_ingest_jobs").select("*").eq("id", jobId).single();
    if (jobError || !job) return json({ error: "Upload niet gevonden." }, 404);
    if (!["uploaded", "failed", "processing"].includes(job.status)) return json({ error: "Deze upload heeft status " + job.status + " en wordt niet opnieuw gestart." }, 409);
    await admin.from("exam_ingest_jobs").update({ status: "processing", stage: "PDF-inventarisatie", progress: 5, message: "Bronbestand wordt gecontroleerd en geïnventariseerd.", error_details: null, updated_at: new Date().toISOString() }).eq("id", jobId);
    await admin.from("exam_ingest_events").insert({ job_id: jobId, level: "info", stage: "PDF-inventarisatie", message: "Inventarisatie gestart." });
    const { data: source, error: downloadError } = await admin.storage.from(BUCKET).download(job.storage_path);
    if (downloadError || !source) throw new Error("Bronbestand kon niet uit de privéopslag worden gelezen: " + (downloadError?.message || "onbekende fout"));
    const sourceBytes = new Uint8Array(await source.arrayBuffer());
    const files: { name: string; bytes: Uint8Array }[] = [];
    if (job.original_filename.toLowerCase().endsWith(".pdf")) files.push({ name: job.original_filename, bytes: sourceBytes });
    else if (job.original_filename.toLowerCase().endsWith(".zip")) {
      const entries = unzipSync(sourceBytes);
      const names = Object.keys(entries).filter(n => !n.endsWith("/") && n.toLowerCase().endsWith(".pdf"));
      if (names.length > MAX_ENTRIES) throw new Error("ZIP bevat " + names.length + " PDF's; maximum is " + MAX_ENTRIES + ".");
      let total = 0;
      for (const name of names) {
        if (name.startsWith("/") || name.split("/").includes("..")) continue;
        const bytes = entries[name]; total += bytes.length;
        if (total > MAX_UNZIPPED) throw new Error("Uitgepakte ZIP is groter dan 1 GB.");
        files.push({ name: name.split("/").pop() || name, bytes });
      }
      if (!files.length) throw new Error("Geen PDF-bestanden gevonden in de ZIP.");
    } else throw new Error("Alleen PDF en ZIP worden ondersteund.");
    const inventory = [];
    let index = 0;
    for (const file of files) {
      index++;
      const result = await inspectPdf(file.bytes, file.name);
      const extractedPath = jobId + "/source/" + String(index).padStart(3, "0") + "-" + file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
      if (job.original_filename.toLowerCase().endsWith(".zip")) {
        const { error: saveError } = await admin.storage.from(BUCKET).upload(extractedPath, file.bytes, { contentType: "application/pdf", upsert: true });
        if (saveError) throw new Error("Uitgepakte PDF kon niet worden opgeslagen: " + saveError.message);
      }
      inventory.push({ ...result, storagePath: job.original_filename.toLowerCase().endsWith(".zip") ? extractedPath : job.storage_path });
      await admin.from("exam_ingest_jobs").update({ progress: Math.min(75, 5 + Math.round(index / files.length * 70)), message: "PDF " + index + " van " + files.length + " geïnventariseerd.", updated_at: new Date().toISOString() }).eq("id", jobId);
    }
    const meta = inventory.length === 1 ? inventory[0] : { archive: true, containedPdfCount: inventory.length, levels: [...new Set(inventory.map(x => x.level).filter(Boolean))], years: [...new Set(inventory.map(x => x.year).filter(Boolean))], periods: [...new Set(inventory.map(x => x.period).filter(Boolean))], documentTypes: [...new Set(inventory.map(x => x.documentType))] };
    const manifest = { schemaVersion: 1, generatedAt: new Date().toISOString(), jobId, originalFilename: job.original_filename, files: inventory };
    const manifestPath = jobId + "/inventory.json";
    const { error: manifestError } = await admin.storage.from(BUCKET).upload(manifestPath, new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }), { contentType: "application/json", upsert: true });
    if (manifestError) throw new Error("Inventaris kon niet worden opgeslagen: " + manifestError.message);
    const lowText = inventory.filter(x => x.pages.some(p => !p.hasExtractableText)).length;
    const summary = { ...meta, inventoryPath: manifestPath, pdfCount: inventory.length, totalPages: inventory.reduce((s, x) => s + x.pageCount, 0), totalTextCharacters: inventory.reduce((s, x) => s + x.totalTextCharacters, 0), filesWithScannedPages: lowText };
    await admin.from("exam_ingest_jobs").update({ status: "review_required", stage: "Inventarisatie afgerond", progress: 100, message: "Inventarisatie klaar: " + summary.pdfCount + " PDF('s), " + summary.totalPages + " pagina's. Inhoudelijke vraag/contextanalyse en beeldsamenstelling volgen nog.", detected_metadata: summary, error_details: null, updated_at: new Date().toISOString() }).eq("id", jobId);
    await admin.from("exam_ingest_events").insert({ job_id: jobId, level: "success", stage: "Inventarisatie afgerond", message: summary.pdfCount + " PDF('s) en " + summary.totalPages + " pagina's geïnventariseerd.", details: summary });
    return json({ ok: true, job_id: jobId, summary, manifest_path: manifestPath });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (jobId) {
      const admin = createClient(SUPABASE_URL, SERVICE_KEY);
      await admin.from("exam_ingest_jobs").update({ status: "failed", stage: "Inventarisatie mislukt", message, error_details: { message }, updated_at: new Date().toISOString() }).eq("id", jobId);
      await admin.from("exam_ingest_events").insert({ job_id: jobId, level: "error", stage: "Inventarisatie mislukt", message });
    }
    return json({ error: message }, 500);
  }
});