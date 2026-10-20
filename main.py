import json
import os
import subprocess
import requests

TARGET_URL = os.environ.get("LAPTOP_SPECS_SERVER_URL", "http://127.0.0.1:8080/")

powershell_script = """
Add-Type -AssemblyName PresentationCore
$isTouch = [System.Windows.Input.Tablet]::TabletDevices | Where-Object { $_.Type -eq 'Touch' }
$touchStatus = if ($isTouch) { "Touch Screen Detected" } else { "No Touch Screen Detected" }

# Safe aggregation helper for scalar metrics from multi-instance objects (like multi-socket CPUs)
$cpuInstances = @(Get-CimInstance Win32_Processor)
$gpuInstances = @(Get-CimInstance Win32_VideoController)
$ramInstances = @(Get-CimInstance Win32_PhysicalMemory)
$diskInstances = @(Get-PhysicalDisk)

# Map RAM type codes to readable text safely
function Get-RamTypeName ($typeCode) {
    switch ($typeCode) {
        20 { "DDR" }
        21 { "DDR2" }
        22 { "DDR2 FB-DIMM" }
        24 { "DDR3" }
        25 { "FBD2" }
        26 { "DDR4" }
        27 { "LPDDR" }
        28 { "LPDDR2" }
        29 { "LPDDR3" }
        30 { "LPDDR4" }
        31 { "LPDDR4X" }
        34 { "DDR5" }
        35 { "LPDDR5" }
        36 { "HBM3" }
        0  { "LPDDR / Soldered" }
        Default { "Unknown ($typeCode)" }
    }
}

# 2. Create a separate function to clean up the manufacturer names if needed
function Get-RamManufacturerName ($manCode) {
    $cleaned = if ($manCode) { $manCode.Trim() } else { "Unknown" }
    switch ($cleaned) {
        "859B"   { "Crucial" }
        "0x859B" { "Crucial" }
        Default  { $cleaned }
    }
}

# Structure sub-arrays explicitly to prevent unexpected layout shifts
$GpuList = foreach ($gpu in $gpuInstances) {
    [PSCustomObject]@{
        Name = $gpu.Name
        VramGB = if ($gpu.AdapterRAM) { [Math]::Round($gpu.AdapterRAM / 1GB, 2) } else { 0 }
    }
}

$RamList = foreach ($ram in $ramInstances) {
    [PSCustomObject]@{
        Slot         = $ram.DeviceLocator
        Manufacturer = Get-RamManufacturerName($ram.Manufacturer)
        SizeGB       = [Math]::Round($ram.Capacity / 1GB, 2)
        SpeedMHz     = $ram.Speed
        Type         = Get-RamTypeName($ram.SMBIOSMemoryType)
    }
}

$DiskList = foreach ($disk in $diskInstances | Where-Object { $_.Model -notmatch 'SanDisk' }) {
    [PSCustomObject]@{
        Model  = $disk.Model.Trim()
        SizeGB = [Math]::Round($disk.Size / 1GB, 2)
        Type   = $disk.MediaType
        Health = $disk.HealthStatus
    }
}

# 1. DEFINE PATH AND GENERATE THE BATTERY REPORT IN XML FORMAT
$xmlPath = "$env:TEMP/batteryreport.xml"
powercfg /batteryreport /XML /OUTPUT $xmlPath | Out-Null

$BatteryList = @()
if (Test-Path $xmlPath) {
    [xml]$Report = Get-Content $xmlPath
    
    # Ensure battery entries exist in the XML report before looping (handles Desktop PCs)
    if ($Report.BatteryReport.Batteries -and $Report.BatteryReport.Batteries.Battery) {
        $BatteryList = foreach ($battery in $Report.BatteryReport.Batteries.Battery) {
            # Extract raw integers for processing math formulas
            $designCap = [int]$battery.DesignCapacity
            $fullChargeCap = [int]$battery.FullChargeCapacity
            
            # Calculate Battery Health percentage safely to avoid division-by-zero on failing/bad hardware
            $healthPct = "0.00%"
            if ($designCap -gt 0) {
                $rawPct = ($fullChargeCap / $designCap) * 100
                $healthPct = "$([Math]::Round($rawPct, 2))%"
            }
            [PSCustomObject]@{
                "Name"                 = $battery.Id
                "Manufacturer"         = $battery.Manufacturer
                "SerialNumber"         = $battery.SerialNumber
                "ManufactureDate"      = $battery.ManufactureDate
                "Chemistry"            = $battery.Chemistry
                "DesignCapacity"      = "$([string]::Format('{0:N0}', [int]$battery.DesignCapacity)) mWh"
                "FullChargeCapacity" = "$([string]::Format('{0:N0}', [int]$battery.FullChargeCapacity)) mWh"
                "BatteryHealth"       = $healthPct
                "CycleCount"          = $battery.CycleCount
            }
        }
    }
    # Clean up the temporary XML file
    Remove-Item $xmlPath -ErrorAction SilentlyContinue
}

$SystemInfo = [PSCustomObject]@{
    # System Details
    Manufacturer            = (Get-CimInstance Win32_ComputerSystem).Manufacturer
    Model                   = (Get-CimInstance Win32_ComputerSystem).Model
    BiosVersion             = (Get-CimInstance Win32_Bios).SMBIOSBIOSVersion
    BiosSerialNumber        = (Get-CimInstance Win32_Bios).SerialNumber
    OSCaption               = (Get-CimInstance Win32_OperatingSystem).Caption
    ProductKey              = (Get-CimInstance -ClassName SoftwareLicensingService -ErrorAction SilentlyContinue).OA3xOriginalProductKey
    OSBuild                 = (Get-ItemProperty "HKLM:/SOFTWARE/Microsoft/Windows NT/CurrentVersion").BuildLabEx
    ComputerName            = $env:COMPUTERNAME
    MachineID               = (Get-ItemProperty -Path "HKLM:/SOFTWARE/Microsoft/SQMClient" -ErrorAction SilentlyContinue).MachineID
    ProductID               = (Get-ItemProperty -Path "HKLM:/SOFTWARE/Microsoft/Windows NT/CurrentVersion" -ErrorAction SilentlyContinue).ProductId
    SystemType              = (Get-CimInstance Win32_ComputerSystem).SystemType
    TouchScreen             = $touchStatus
    
    # CPU Specs (Handles Multi-CPU nodes natively)
    CpuName                 = ($cpuInstances | Select-Object -First 1).Name
    CpuMaxClockSpeed        = ($cpuInstances | Measure-Object -Property MaxClockSpeed -Maximum).Maximum
    CpuCores                = ($cpuInstances | Measure-Object -Property NumberOfCores -Sum).Sum
    CpuLogicalProcessors    = ($cpuInstances | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
    CpuVirtualizationEnabled= ($cpuInstances | Select-Object -First 1).VirtualizationFirmwareEnabled
    CpuCacheSizeKB          = @(Get-CimInstance Win32_CacheMemory | ForEach-Object { $_.InstalledSize })
    
    # Enforce arrays explicitly with @() to stop single-item flattening shifts
    GPUs                    = @($GpuList)
    RAM_Sticks              = @($RamList)
    RamTotalGB              = if ($ramInstances) { [Math]::Round(($ramInstances | Measure-Object -Property Capacity -Sum).Sum / 1GB, 2) } else { 0 }
    Disks                   = @($DiskList)
    Batteries               = @($BatteryList)
    
    # Monitor & Display
    MonitorDeviceIDs        = @(Get-CimInstance -ClassName Win32_PnPSignedDriver | Where-Object { $_.DeviceClass -eq "MONITOR" } | ForEach-Object { $_.DeviceID }) -join ', '
    Resolution              = "$(([int[]]($gpuInstances | Where-Object { $_.CurrentHorizontalResolution } | Select-Object -First 1 -ExpandProperty CurrentHorizontalResolution))) x $([int[]]($gpuInstances | Where-Object { $_.CurrentVerticalResolution } | Select-Object -First 1 -ExpandProperty CurrentVerticalResolution))"
    MonitorSizesInches      = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBasicDisplayParams | ForEach-Object { [Math]::Round([Math]::Sqrt([Math]::Pow($_.MaxHorizontalImageSize, 2) + [Math]::Pow($_.MaxVerticalImageSize, 2)) / 2.54, 1) }) -join ', '
    RefreshRateHz           = ($gpuInstances | Where-Object { $_.CurrentRefreshRate } | Select-Object -First 1).CurrentRefreshRate
    
    Timestamp               = (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
}

$SystemInfo | ConvertTo-Json -Depth 4
"""

# Execute the PowerShell script
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", "-"],
    input=powershell_script,
    capture_output=True,
    text=True
)

if result.returncode == 0:
    try:
        # Load the output data as JSON
        data = json.loads(result.stdout)
        data["buyPrice"] = None
        data["sellPrice"] = None
        data["at"] = os.environ.get("LAPTOP_SPECS_LOCATION", "")
        data["notes"] = ""
        print("Successfully generated system specs data. Sending to server...")
        
        # Send the JSON payload via an HTTP POST request
        response = requests.post(TARGET_URL, json=data, timeout=10)
        
        # Check if the server received it successfully
        if response.status_code == 200:
            print(f"Data successfully sent to {TARGET_URL}")
        else:
            print(f"Server responded with status code: {response.status_code}")
            
    except json.JSONDecodeError:
        print("Failed to decode PowerShell output as JSON.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect or send data to {TARGET_URL}.\nError: {e}")
else:
    print("PowerShell execution failed:\n", result.stderr)