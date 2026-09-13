import { useCallback, useRef, useState } from 'react'
import {
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/layout/PageHeader'
import AnalysisProgress from '../components/primitives/AnalysisProgress'
import Card from '../components/primitives/Card'
import ProductThumb from '../components/primitives/ProductThumb'
import { useAppData } from '../context/AppDataContext'
import useEnrichmentJob from '../hooks/useEnrichmentJob'
import { previewCsv, uploadCsv } from '../lib/api'
import { formatPrice } from '../lib/format'

const REQUIRED_COLUMNS = [
  'Handle',
  'Title',
  'Type',
  'Tags',
  'Vendor',
  'Variant Price',
  'Variant Inventory Qty',
]

// A very large catalog CSV could group into thousands of products — render
// only the first page of them so the preview never hangs the tab, and say
// plainly how many are hidden.
const PREVIEW_RENDER_CAP = 60

// idle -> previewing -> preview -> importing -> analysing -> success
//                     -> preview-error
//                                  -> import-error
//
// `analysing` is the stage added for enrichment. Importing a CSV is fast, but
// reading every product with a model is minutes, so the two are separated:
// the import is committed first (the catalog is real and browsable straight
// away) and analysis then runs as a pollable background job.
export default function Upload() {
  const { catalog } = useAppData()
  const navigate = useNavigate()
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState(null)
  const [stage, setStage] = useState('idle')
  const [preview, setPreview] = useState(null) // {ok:true, products, products_loaded, variants, warnings}
  const [errorResult, setErrorResult] = useState(null) // {error, detail}
  const [importResult, setImportResult] = useState(null) // {ok:true, products_loaded, variants, warnings}
  const inputRef = useRef(null)

  const enrichment = useEnrichmentJob({
    onComplete: () => {
      setStage('success')
      catalog.reload()
    },
  })

  const reset = useCallback(() => {
    setFile(null)
    setStage('idle')
    setPreview(null)
    setErrorResult(null)
    setImportResult(null)
    enrichment.reset()
    if (inputRef.current) inputRef.current.value = ''
  }, [enrichment])

  const runPreview = useCallback(async (chosenFile) => {
    if (!chosenFile) return
    setFile(chosenFile)
    setPreview(null)
    setErrorResult(null)
    setStage('previewing')
    try {
      const { data } = await previewCsv(chosenFile)
      if (data?.ok) {
        setPreview(data)
        setStage('preview')
      } else {
        setErrorResult(data)
        setStage('preview-error')
      }
    } catch (err) {
      setErrorResult({ error: err.message || 'Could not reach the server.', detail: [] })
      setStage('preview-error')
    }
  }, [])

  const runImport = useCallback(async () => {
    if (!file) return
    setStage('importing')
    setErrorResult(null)
    try {
      const { data } = await uploadCsv(file)
      if (data?.ok) {
        setImportResult(data)
        // A successful upload changes the real catalog size shown in the
        // Topbar and on the Catalog page — refetch so they don't go stale.
        catalog.reload()
        // Roll straight into analysis. The seller has just handed over a new
        // catalog; making them find and press a second button to make it
        // useful is a step with no decision in it.
        setStage('analysing')
        enrichment.start()
      } else {
        setErrorResult(data)
        setStage('import-error')
      }
    } catch (err) {
      setErrorResult({ error: err.message || 'Could not reach the server.', detail: [] })
      setStage('import-error')
    }
  }, [file, catalog, enrichment])

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      setDragOver(false)
      const dropped = e.dataTransfer.files?.[0]
      if (dropped) runPreview(dropped)
    },
    [runPreview],
  )

  const showDropzone = stage === 'idle' || stage === 'previewing'

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Upload"
        subtitle="Import your Shopify product CSV to build the catalog."
      />

      {showDropzone && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <Card className="h-auto min-h-[300px] lg:col-span-2" padded={false}>
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={clsx(
                'flex h-full min-h-[300px] flex-col items-center justify-center gap-3 rounded-card border-2 border-dashed p-8 text-center transition-colors',
                dragOver ? 'border-pastel-purple-ink bg-pastel-purple/20' : 'border-hairline',
              )}
            >
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-pastel-blue text-pastel-blue-ink">
                <UploadCloud size={26} strokeWidth={2} />
              </span>
              <div>
                <p className="text-base font-semibold text-ink">Drag and drop your CSV here</p>
                <p className="mt-1 text-sm text-muted">or browse files from your computer</p>
              </div>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={stage === 'previewing'}
                className="rounded-pill bg-cta px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Browse files
              </button>
              <input
                ref={inputRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => runPreview(e.target.files?.[0])}
              />
              {file && stage === 'previewing' && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-muted">
                  <FileSpreadsheet size={13} />
                  {file.name}
                </p>
              )}
            </div>
          </Card>

          <Card title="Required columns" subtitle="Your CSV must include these headers" className="h-auto min-h-[300px]">
            <ul className="flex flex-col gap-2">
              {REQUIRED_COLUMNS.map((col) => (
                <li
                  key={col}
                  className="flex items-center gap-2 rounded-chip bg-cream px-3 py-2 text-sm font-medium text-ink"
                >
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pastel-purple-ink" />
                  {col}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      {stage === 'previewing' && (
        <Card className="h-[120px]">
          <div className="flex h-full items-center justify-center gap-2.5 text-sm font-medium text-muted">
            <Loader2 size={18} className="animate-spin text-pastel-purple-ink" />
            Reading and validating {file?.name}…
          </div>
        </Card>
      )}

      {(stage === 'preview-error' || stage === 'import-error') && errorResult && (
        <Card className="h-auto">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-negative-bg text-negative">
              <XCircle size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-base font-semibold text-ink">
                {stage === 'import-error' ? 'Import failed' : errorResult.error || 'Upload failed'}
              </p>
              {stage === 'import-error' && errorResult.error && (
                <p className="mt-1 text-sm text-muted">{errorResult.error}</p>
              )}
              {Array.isArray(errorResult.detail) && errorResult.detail.length > 0 && (
                <>
                  <p className="mt-1 text-sm text-muted">Missing required columns:</p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {errorResult.detail.map((col) => (
                      <li
                        key={col}
                        className="rounded-full bg-negative-bg px-3 py-1 text-xs font-medium text-negative"
                      >
                        {col}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className="mt-4 flex gap-2.5">
                {stage === 'import-error' && preview && (
                  <button
                    type="button"
                    onClick={() => setStage('preview')}
                    className="rounded-pill border border-hairline bg-card px-4 py-2 text-sm font-semibold text-ink hover:bg-cream"
                  >
                    Back to preview
                  </button>
                )}
                <button
                  type="button"
                  onClick={reset}
                  className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
                >
                  Choose another file
                </button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {(stage === 'preview' || stage === 'importing') && preview && (
        <>
          <Card className="h-auto">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1">
                <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                  <FileSpreadsheet size={15} className="text-pastel-purple-ink" />
                  {file?.name} — nothing has been imported yet
                </p>
                <p className="text-xs text-muted">
                  {preview.variants} CSV row{preview.variants === 1 ? '' : 's'} grouped into{' '}
                  <span className="font-semibold text-ink">{preview.products_loaded}</span> product
                  {preview.products_loaded === 1 ? '' : 's'} by Handle (Shopify exports one row per variant).
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:max-w-md">
                <div className="rounded-chip bg-cream px-4 py-3">
                  <p className="text-xs text-muted">Products</p>
                  <p className="mt-0.5 text-xl font-bold text-ink">{preview.products_loaded}</p>
                </div>
                <div className="rounded-chip bg-cream px-4 py-3">
                  <p className="text-xs text-muted">Variant rows</p>
                  <p className="mt-0.5 text-xl font-bold text-ink">{preview.variants}</p>
                </div>
              </div>

              {Array.isArray(preview.warnings) && preview.warnings.length > 0 && (
                <div>
                  <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
                    <AlertTriangle size={14} className="text-pastel-yellow-ink" />
                    Warnings
                  </p>
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {preview.warnings.map((w) => (
                      <li
                        key={w}
                        className="rounded-chip bg-pastel-yellow/40 px-3 py-2 text-sm text-pastel-yellow-ink"
                      >
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2.5 border-t border-hairline pt-4">
                <button
                  type="button"
                  onClick={runImport}
                  disabled={stage === 'importing'}
                  className="flex items-center gap-2 rounded-pill bg-cta px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {stage === 'importing' ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={15} strokeWidth={2.25} />
                  )}
                  {stage === 'importing' ? 'Importing…' : 'Import catalog'}
                </button>
                <button
                  type="button"
                  onClick={reset}
                  disabled={stage === 'importing'}
                  className="flex items-center gap-2 rounded-pill border border-hairline bg-card px-5 py-2.5 text-sm font-semibold text-ink hover:bg-cream disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <X size={15} strokeWidth={2.25} />
                  Cancel
                </button>
              </div>
            </div>
          </Card>

          <Card
            title="Products in this file"
            subtitle={
              preview.products.length > PREVIEW_RENDER_CAP
                ? `Showing the first ${PREVIEW_RENDER_CAP} of ${preview.products.length}`
                : `${preview.products.length} product${preview.products.length === 1 ? '' : 's'}`
            }
            className="h-[480px]"
            bodyClassName="overflow-y-auto pr-1"
          >
            {preview.products.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-muted">
                This file contains a header row but no product rows.
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {preview.products.slice(0, PREVIEW_RENDER_CAP).map((p) => (
                    <div
                      key={p.product_id}
                      className="flex min-w-0 items-center gap-3 rounded-chip border border-hairline p-3"
                    >
                      <ProductThumb src={p.image_src} name={p.title} size="lg" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-ink">{p.title}</p>
                        <p className="truncate text-xs text-muted">
                          {p.product_type} · {p.vendor}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-muted-2">
                          {p.variants} variant{p.variants === 1 ? '' : 's'} · {p.current_stock} in stock ·{' '}
                          {formatPrice(p.price)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
                {preview.products.length > PREVIEW_RENDER_CAP && (
                  <p className="mt-3 text-center text-xs text-muted">
                    +{preview.products.length - PREVIEW_RENDER_CAP} more product
                    {preview.products.length - PREVIEW_RENDER_CAP === 1 ? '' : 's'} not shown — they will still
                    be imported.
                  </p>
                )}
              </>
            )}
          </Card>
        </>
      )}

      {stage === 'analysing' && (
        <Card className="h-auto">
          {enrichment.error ? (
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-pastel-yellow text-pastel-yellow-ink">
                <AlertTriangle size={20} strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold text-ink">
                  Your catalog was imported, but analysis did not finish
                </p>
                <p className="mt-1 text-sm text-muted">{enrichment.error}</p>
                <p className="mt-1 text-sm text-muted">
                  Your products are saved and browsable. You can run the analysis
                  again from the Catalog page at any time.
                </p>
                <div className="mt-4 flex flex-wrap gap-2.5">
                  <button
                    type="button"
                    onClick={() => enrichment.start()}
                    className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
                  >
                    Try again
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/catalog')}
                    className="rounded-pill border border-hairline bg-card px-4 py-2 text-sm font-semibold text-ink hover:bg-cream"
                  >
                    Go to catalog
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <AnalysisProgress job={enrichment.job} />
          )}
        </Card>
      )}

      {stage === 'success' && importResult && (
        <Card className="h-auto">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-positive-bg text-positive">
              <CheckCircle2 size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-base font-semibold text-ink">Catalog imported and analysed</p>
              {enrichment.job?.result?.store_type && (
                <p className="mt-1 text-sm text-muted">
                  Recognised as{' '}
                  <span className="font-medium text-ink">
                    {enrichment.job.result.store_type}
                  </span>
                  {typeof enrichment.job.result.with_occasions === 'number' && (
                    <>
                      {' '}
                      · {enrichment.job.result.with_occasions} product
                      {enrichment.job.result.with_occasions === 1 ? '' : 's'} matched to
                      occasions
                    </>
                  )}
                </p>
              )}
              <div className="mt-3 grid grid-cols-2 gap-3 sm:max-w-sm">
                <div className="rounded-chip bg-cream px-4 py-3">
                  <p className="text-xs text-muted">Products loaded</p>
                  <p className="mt-0.5 text-xl font-bold text-ink">{importResult.products_loaded}</p>
                </div>
                <div className="rounded-chip bg-cream px-4 py-3">
                  <p className="text-xs text-muted">Variants</p>
                  <p className="mt-0.5 text-xl font-bold text-ink">{importResult.variants}</p>
                </div>
              </div>
              {Array.isArray(importResult.warnings) && importResult.warnings.length > 0 && (
                <div className="mt-4">
                  <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
                    <AlertTriangle size={14} className="text-pastel-yellow-ink" />
                    Warnings
                  </p>
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {importResult.warnings.map((w) => (
                      <li
                        key={w}
                        className="rounded-chip bg-pastel-yellow/40 px-3 py-2 text-sm text-pastel-yellow-ink"
                      >
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2.5">
                <button
                  type="button"
                  onClick={() => navigate('/catalog')}
                  className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
                >
                  View catalog
                </button>
                <button
                  type="button"
                  onClick={reset}
                  className="rounded-pill border border-hairline bg-card px-4 py-2 text-sm font-semibold text-ink hover:bg-cream"
                >
                  Import another file
                </button>
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
