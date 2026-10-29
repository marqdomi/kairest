# Builds kairest.ico (multi-size, PNG-compressed) from icon-512.png.
# Run once from the repo; the .ico is committed, this script is not needed at install time.
Add-Type -AssemblyName System.Drawing

$src = "C:\Users\USER\kairest\backend\static\img\icon-512.png"
$outIco = "C:\Users\USER\kairest\windows-installer\assets\kairest.ico"
$sizes = @(16, 32, 48, 256)

$srcImg = [System.Drawing.Image]::FromFile($src)

$entries = @()
foreach ($size in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.DrawImage($srcImg, 0, 0, $size, $size)
    $g.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $entries += [PSCustomObject]@{ Size = $size; Png = $ms.ToArray() }
    $bmp.Dispose()
}
$srcImg.Dispose()

$fs = New-Object System.IO.FileStream($outIco, [System.IO.FileMode]::Create)
$bw = New-Object System.IO.BinaryWriter($fs)

# ICONDIR: reserved(2)=0, type(2)=1, count(2)
$bw.Write([UInt16]0)
$bw.Write([UInt16]1)
$bw.Write([UInt16]$entries.Count)

$offset = 6 + (16 * $entries.Count)
foreach ($e in $entries) {
    $wh = if ($e.Size -eq 256) { 0 } else { $e.Size }  # 0 means 256 in ICO format
    $bw.Write([Byte]$wh)          # width
    $bw.Write([Byte]$wh)          # height
    $bw.Write([Byte]0)            # color palette
    $bw.Write([Byte]0)            # reserved
    $bw.Write([UInt16]1)          # color planes
    $bw.Write([UInt16]32)         # bits per pixel
    $bw.Write([UInt32]$e.Png.Length)  # size of image data
    $bw.Write([UInt32]$offset)        # offset of image data
    $offset += $e.Png.Length
}
foreach ($e in $entries) {
    $bw.Write($e.Png)
}
$bw.Close()
$fs.Close()

Write-Host "Icon written to $outIco"
