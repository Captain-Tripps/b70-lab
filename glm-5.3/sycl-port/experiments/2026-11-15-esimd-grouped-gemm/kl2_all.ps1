# round 2: is the IQ2_S format exact (mode 2 = joint_matrix K order, must give the joint path's bytes) and its quality (mode 1)
$X='<work>\experiments\claude-glm-l12-20261115'
$old='<work>\rt-glm-q6al-20261114\generate.exe'; $c1="$X\tree\link\generate.exe"; $c2="$X\tree2\link\generate.exe"
foreach ($case in 'code','long32k') {
  foreach ($a in @(@('j',$old,''),@('c1m2',$c1,'2'),@('c2m2',$c2,'2'),@('c2m1',$c2,'1'),@('c1m1',$c1,'1'))) {
    try { $r = & "$X\kl_l12.ps1" -Sub kl2 -Case $case -Exe $a[1] -Esimd $a[2] -Tag $a[0] } catch { $r = "$case-$($a[0]) FAILED $($_.Exception.Message)" }
    $r
    if ($r -notmatch 'EXIT 0') { 'STOPPED'; exit 1 }
  }
}
'KL_DONE'
