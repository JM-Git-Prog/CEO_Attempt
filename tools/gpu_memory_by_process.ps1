# Per-process VRAM via Windows GPU performance counters.
# This is the same source as Task Manager's "Dedicated GPU memory" column,
# and it works when nvidia-smi reports [N/A] on a GeForce card.
# READ-ONLY: reads counters, changes nothing.

$samples = (Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples

if (-not $samples) {
    Write-Host "No GPU counters returned. Open Task Manager > Details, right-click a"
    Write-Host "column header > Select columns > tick 'Dedicated GPU memory' instead."
    return
}

$rows = foreach ($s in $samples) {
    if ($s.InstanceName -match 'pid_(\d+)') {
        [pscustomobject]@{
            ProcessId = [int]$Matches[1]
            Bytes     = [double]$s.CookedValue
        }
    }
}

$rows |
  Group-Object ProcessId |
  ForEach-Object {
      $procId = [int]$_.Name
      $proc   = Get-Process -Id $procId -ErrorAction SilentlyContinue
      [pscustomobject]@{
          VRAM_GB = [math]::Round((($_.Group | Measure-Object Bytes -Sum).Sum) / 1GB, 2)
          PID     = $procId
          Name    = if ($proc) { $proc.ProcessName } else { '(exited)' }
          Path    = if ($proc) { $proc.Path } else { '' }
      }
  } |
  Where-Object { $_.VRAM_GB -ge 0.1 } |
  Sort-Object VRAM_GB -Descending |
  Select-Object -First 25 |
  Format-Table -AutoSize

$total = [math]::Round((($rows | Measure-Object Bytes -Sum).Sum) / 1GB, 2)
Write-Host ""
Write-Host "Total dedicated VRAM attributed to processes: $total GB"
