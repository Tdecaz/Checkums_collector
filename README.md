# Checkums Collector

Tkinter application that scans PDF files to collect filenames and SHA-1 checksums. Results can be reviewed and exported to Excel.

## Features

- Scans all PDFs in a selected input folder.
- Detects filenames with common extensions (jar, xml, json, etc.) and special names like "RTP 96" or "Paytable".
- Extracts SHA-1 checksums even when split across tokens.
- Automatically pairs obvious filename/checksum matches and queues ambiguous cases.
- Review window lets you join fragments, manually pair items, mark entries as reviewed, or discard them.
- Exports confirmed matches and a log of ambiguous items to an Excel workbook.

## Requirements

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Downloading the project

You can obtain the source code either via **Git** or by downloading a ZIP
archive from your hosting provider (e.g., GitHub, GitLab).

### Clone with Git

```bash
git clone <repository-url>
cd Checkums_collector
```

Replace `<repository-url>` with the HTTPS or SSH address of your fork or the
original repository.

### Download as ZIP

If you prefer not to use Git, download the ZIP archive from the repository
webpage, extract it, and open a terminal inside the extracted folder before
continuing with the usage instructions below.

## Making commits

1. Create a feature branch so your changes stay isolated:

   ```bash
   git checkout -b feature/short-description
   ```

2. Make your edits (e.g., update the parser or improve the GUI) and verify that
   tests or linting still pass.

3. Stage the files you want to include in the commit:

   ```bash
   git add <file1> <file2> ...
   ```

4. Create the commit with a concise message:

   ```bash
   git commit -m "Describe your change"
   ```

5. Push the branch to your remote and open a pull request if required:

   ```bash
   git push origin feature/short-description
   ```

These steps work the same whether you cloned the repository directly or are
working on a fork.

## Usage

### 1. Launch the application

Run the Tkinter GUI from the project root:

```bash
python main.py
```

When the window opens you will see:

- **Input Folder** field and **Browse…** button for picking the directory that contains the PDF files to scan.
- **Output Folder** field and **Browse…** button where the exported Excel workbook will be saved.
- **Start Scan** button, a progress bar, and textual status that shows which PDF is currently being analysed.
- A table that will eventually list the confirmed filename / checksum matches, and counters for how many ambiguous entries still need review.

Both the input and output folders must be selected before you can start a scan.

### 2. Run the scan

1. Click **Browse…** next to *Input Folder* and choose the directory with the PDFs you want to analyse.
2. Click **Browse…** next to *Output Folder* and choose or create an empty folder where the Excel workbook should be generated.
3. Press **Start Scan**. The app will iterate through every PDF in the input folder. While the scan runs you will see:
   - The progress bar advance per PDF ("Processing file X of Y").
   - The results table filling with confident filename/SHA-1 pairs as they are detected.
   - A counter of ambiguous items that require manual attention.

You can cancel the scan at any time with **Stop Scan**; the data collected so far remains available for review.

### 3. Review ambiguous items

Once the scan finishes (or whenever there are ambiguous entries), click **Review Ambiguous Items** to open the review panel. The panel presents each unresolved case with the surrounding PDF context and allows you to:

- **Join fragments** – merge split filename or checksum pieces into a single value.
- **Pair manually** – choose which filename fragment belongs with which checksum.
- **Discard** – drop entries that are not valid matches.
- **Mark reviewed** – accept an entry as-is without further modification.

Use Shift/Ctrl-click to select multiple rows and apply the same action in bulk. Confirmed items move into the main results table; discarded ones are tracked separately so they do not appear in the export.

### 4. Export the results

After clearing all ambiguous items, click **Export to Excel**. The application creates an `.xlsx` workbook in the output folder with two sheets:

1. **Results** – columns for PDF name, page number, filename, SHA-1 checksum, and review status/notes.
2. **Ambiguous Items** – optional log of anything you chose to discard or leave unresolved.

If a file with the same name already exists in the output folder you will be prompted before overwriting.

### 5. Subsequent runs

To process another batch of PDFs, change the input/output folder selections and click **Start Scan** again. The interface resets the previous results automatically.

## Troubleshooting

- **No PDFs detected** – ensure the selected input folder contains PDF files and that they are not encrypted.
- **Missing dependencies** – verify `pip install -r requirements.txt` completed successfully and that you are using Python 3.9 or newer.
- **Excel export fails** – confirm you have write permissions to the output folder and that the workbook is not open in another program.
