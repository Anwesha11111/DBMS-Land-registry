/**
 * frontend/js/viewer3d.js
 * Three.js 3D spatial plot visualizer.
 * Projects WGS84 GeoJSON polygons to local metric coordinates.
 * Extrudes 3D mesh representations with real-time state coloring:
 * - Green = Clear with active Ask
 * - Blue = Clear not listed
 * - Amber = Pending
 * - Red = Disputed
 * - White outline = Owned by current logged-in user
 */

export class PlotViewer3D {
  constructor(canvasContainerId, onPlotSelectCallback) {
    this.container = document.getElementById(canvasContainerId);
    this.onPlotSelect = onPlotSelectCallback;
    this.plotsData = [];
    this.plotMeshes = new Map();
    this.centroid = { lon: 77.5946, lat: 12.9716 }; // Bengaluru default
    this.currentUserOwnerId = null;
    this.currentUserRole = 'public'; // 'public' | 'buyer' | 'owner_seller' | 'registry_admin' | 'court'
    this.viewFilter = 'all'; // 'all' | 'available' | 'my_plots' | 'pending' | 'disputed'
    this.mapBasemap = 'satellite'; // 'satellite' | 'terrain' | 'streets' | 'dark'
    this.groundMesh = null;
    this.satelliteTexture = null;

    this.initScene();
    this.initInteraction();
    this.animate();
  }

  setCurrentUser(ownerId, role = 'buyer') {
    this.currentUserOwnerId = ownerId;
    this.currentUserRole = role;
    this.updateMeshStyles();
  }

  setViewFilter(filter) {
    this.viewFilter = filter;
    this.updateMeshStyles();
  }

  initScene() {
    // 1. WebGL2 Check
    const canvas = document.createElement('canvas');
    const gl2 = canvas.getContext('webgl2');
    if (!gl2) {
      this.container.innerHTML = `
        <div style="padding: 40px; color: #ef4444; text-align: center;">
          <h2>WebGL 2.0 Not Supported</h2>
          <p>Please use a modern browser with hardware acceleration enabled to view the 3D land parcels.</p>
        </div>`;
      return;
    }

    // 2. Three.js Setup: Bright sunny sky & modern atmospheric look
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x93c5fd); // Light atmospheric sky blue
    this.scene.fog = new THREE.FogExp2(0x93c5fd, 0.0006);

    const width = this.container.clientWidth;
    const height = this.container.clientHeight;

    this.camera = new THREE.PerspectiveCamera(45, width / height, 1, 3500);
    this.camera.position.set(0, 180, 260);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.container.appendChild(this.renderer.domElement);

    // 3. OrbitControls
    if (typeof THREE.OrbitControls !== 'undefined') {
      this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxPolarAngle = Math.PI / 2 - 0.02; // Keep above ground
      this.controls.minDistance = 20;
      this.controls.maxDistance = 1200;
    }

    // 4. Natural Sunlight & Environmental Illumination
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0x475569, 0.85);
    hemiLight.position.set(0, 300, 0);
    this.scene.add(hemiLight);

    const sunLight = new THREE.DirectionalLight(0xfffaf0, 1.35);
    sunLight.position.set(250, 400, 180);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.width = 2048;
    sunLight.shadow.mapSize.height = 2048;
    sunLight.shadow.camera.near = 10;
    sunLight.shadow.camera.far = 1200;
    const d = 400;
    sunLight.shadow.camera.left = -d;
    sunLight.shadow.camera.right = d;
    sunLight.shadow.camera.top = d;
    sunLight.shadow.camera.bottom = -d;
    sunLight.shadow.bias = -0.0005;
    this.scene.add(sunLight);

    // Subtle Cadastre Reference Grid
    const grid = new THREE.GridHelper(1600, 80, 0x94a3b8, 0xcfd8dc);
    grid.position.y = 0.1;
    this.grid = grid;
    this.scene.add(grid);

    // 5. High-Resolution Satellite & Terrain Ground Canvas
    this.initGroundLayer();

    // Responsive resize
    window.addEventListener('resize', () => this.onWindowResize());
  }

  setBasemap(mode) {
    this.mapBasemap = mode;
    this.updateGroundTexture();
  }

  initGroundLayer() {
    const groundGeo = new THREE.PlaneGeometry(2400, 2400, 64, 64);
    groundGeo.rotateX(-Math.PI / 2); // Horizontal ground
    const groundMat = new THREE.MeshStandardMaterial({
      roughness: 0.85,
      metalness: 0.05,
      color: 0xffffff
    });

    this.groundMesh = new THREE.Mesh(groundGeo, groundMat);
    this.groundMesh.position.y = 0;
    this.groundMesh.receiveShadow = true;
    this.scene.add(this.groundMesh);
    this.updateGroundTexture();
  }

  updateGroundTexture() {
    if (!this.groundMesh) return;

    const size = 1024;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');

    // Vibrant Aerial Cartography with Park Greenery, Roads and Subdivision Blocks
    const grad = ctx.createLinearGradient(0, 0, size, size);
    grad.addColorStop(0, '#365314');   // Lush forest green
    grad.addColorStop(0.3, '#3f6212'); // Rich lawn green
    grad.addColorStop(0.7, '#2e491a'); // Natural turf
    grad.addColorStop(1, '#4d7c0f');   // Vibrant parkland
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);

    // Land parcel zoning tiles
    ctx.fillStyle = 'rgba(255, 255, 255, 0.04)';
    for (let x = 60; x < size; x += 180) {
      for (let y = 60; y < size; y += 180) {
        ctx.fillRect(x, y, 140, 140);
      }
    }

    // Procedural trees & landscape foliage
    ctx.fillStyle = 'rgba(20, 50, 15, 0.55)';
    for (let i = 0; i < 450; i++) {
      const x = Math.random() * size;
      const y = Math.random() * size;
      const r = Math.random() * 20 + 5;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }

    // Asphalt Avenue Grid with Sidewalks
    const roadCoords = [140, 360, 580, 800];
    
    // Sidewalks
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 34;
    roadCoords.forEach(c => {
      ctx.beginPath(); ctx.moveTo(0, c); ctx.lineTo(size, c); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(c, 0); ctx.lineTo(c, size); ctx.stroke();
    });

    // Asphalt Road Surface
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 22;
    roadCoords.forEach(c => {
      ctx.beginPath(); ctx.moveTo(0, c); ctx.lineTo(size, c); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(c, 0); ctx.lineTo(c, size); ctx.stroke();
    });

    // Yellow Lane Centerlines
    ctx.strokeStyle = '#fef08a';
    ctx.lineWidth = 2.5;
    ctx.setLineDash([14, 14]);
    roadCoords.forEach(c => {
      ctx.beginPath(); ctx.moveTo(0, c); ctx.lineTo(size, c); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(c, 0); ctx.lineTo(c, size); ctx.stroke();
    });
    ctx.setLineDash([]);

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(1, 1);
    this.groundMesh.material.map = texture;
    this.groundMesh.material.needsUpdate = true;
  }

  onWindowResize() {
    if (!this.renderer || !this.container) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // Equirectangular projection from lon/lat to local meters
  projectToMeters(lon, lat) {
    const latRad = (this.centroid.lat * Math.PI) / 180;
    const x = (lon - this.centroid.lon) * 111320 * Math.cos(latRad);
    const z = -(lat - this.centroid.lat) * 110540;
    return { x, z };
  }

  loadPlots(plots) {
    this.plotsData = plots;

    // Clear existing plot meshes
    for (const [_, group] of this.plotMeshes) {
      this.scene.remove(group);
    }
    this.plotMeshes.clear();

    if (!plots || plots.length === 0) return;

    // Calculate global centroid from average coordinates across all plots
    try {
      let sumLon = 0, sumLat = 0, count = 0;
      plots.forEach(p => {
        if (p.geojson && p.geojson.coordinates && p.geojson.coordinates[0]) {
          p.geojson.coordinates[0].forEach(c => {
            sumLon += c[0];
            sumLat += c[1];
            count++;
          });
        }
      });
      if (count > 0) {
        this.centroid = { lon: sumLon / count, lat: sumLat / count };
      }
    } catch (e) {
      this.centroid = { lon: 77.6350, lat: 12.9700 };
    }

    plots.forEach(plot => this.createPlotMesh(plot));

    // Auto-fit camera to parcels centroid
    if (this.controls) {
      this.controls.target.set(0, 0, 0);
      this.camera.position.set(0, 160, 240);
      this.camera.lookAt(0, 0, 0);
      this.controls.update();
    }
  }

  createPlotMesh(plot) {
    if (!plot.geojson || !plot.geojson.coordinates) return;

    const coords = plot.geojson.coordinates[0];
    const shape = new THREE.Shape();

    coords.forEach((coord, index) => {
      const pt = this.projectToMeters(coord[0], coord[1]);
      if (index === 0) {
        shape.moveTo(pt.x, pt.z);
      } else {
        shape.lineTo(pt.x, pt.z);
      }
    });

    const extrudeSettings = {
      depth: 12,
      bevelEnabled: true,
      bevelSegments: 3,
      steps: 1,
      bevelSize: 1.2,
      bevelThickness: 1.2
    };

    const geometry = new THREE.ExtrudeGeometry(shape, extrudeSettings);
    geometry.rotateX(Math.PI / 2); // Orient horizontally

    const color = this.getPlotColor(plot);
    const material = new THREE.MeshStandardMaterial({
      color: color,
      roughness: 0.25,
      metalness: 0.15,
      transparent: true,
      opacity: 0.94
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.y = 1;
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // Glowing border outline
    const edges = new THREE.EdgesGeometry(geometry);
    const isOwner = this.currentUserOwnerId && plot.owner_id === this.currentUserOwnerId;
    const lineMaterial = new THREE.LineBasicMaterial({
      color: isOwner ? 0xffffff : 0x0284c7,
      linewidth: isOwner ? 3 : 1.5
    });
    const edgeLines = new THREE.LineSegments(edges, lineMaterial);
    edgeLines.position.y = 1;

    // Add a miniature 3D architectural villa / building pavilion on clear plots to make them visually impressive
    const group = new THREE.Group();
    group.add(mesh);
    group.add(edgeLines);

    if (plot.status === 'Clear') {
      const houseGeo = new THREE.BoxGeometry(14, 10, 14);
      const houseMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 });
      const houseMesh = new THREE.Mesh(houseGeo, houseMat);
      houseMesh.position.set(0, 18, 0);
      houseMesh.castShadow = true;
      group.add(houseMesh);

      // Roof
      const roofGeo = new THREE.ConeGeometry(12, 6, 4);
      roofGeo.rotateY(Math.PI / 4);
      const roofMat = new THREE.MeshStandardMaterial({ color: 0x0284c7, roughness: 0.4 });
      const roofMesh = new THREE.Mesh(roofGeo, roofMat);
      roofMesh.position.set(0, 26, 0);
      roofMesh.castShadow = true;
      group.add(roofMesh);
    }
    group.userData = { plot: plot, mesh: mesh, edgeLines: edgeLines };

    this.scene.add(group);
    this.plotMeshes.set(plot.plot_id, group);
  }

  getPlotColor(plot) {
    const isOwner = this.currentUserOwnerId && plot.owner_id === this.currentUserOwnerId;
    const isListed = plot.status === 'Clear' && plot.active_ask !== null && plot.active_ask !== undefined;

    // 1. Seller Map Lens: Emphasize parcels owned by seller
    if (this.currentUserRole === 'owner_seller') {
      if (isOwner) {
        return isListed ? 0x10b981 : 0x8b5cf6; // Emerald Green if Listed for sale, Vivid Violet if Owned but not yet listed
      }
      // Non-owned plots appear dimmed slate
      return isListed ? 0x334155 : 0x1e293b;
    }

    // 2. Admin / Municipal Authority Map Lens: Emphasize verification workflow
    if (this.currentUserRole === 'registry_admin' || this.currentUserRole === 'court' || this.currentUserRole === 'sys_admin') {
      if (plot.status === "Pending") return 0xf59e0b;  // Glowing Amber (Needs Admin Approval!)
      if (plot.status === "Disputed") return 0xef4444; // Bright Red (Court Injunction Active)
      if (isListed) return 0x22c55e;                   // Green (Clear & Listed)
      return 0x38bdf8;                                 // Sky Blue (Clear & Idle)
    }

    // 3. Customer / Buyer Map Lens: Highlighting parcels available for purchase
    if (this.currentUserRole === 'buyer' || this.currentUserRole === 'public') {
      if (isListed) return 0x22c55e;   // Bright Emerald Green (BUY NOW - Available for purchase)
      if (plot.status === "Clear") return 0x1e293b; // Dim Charcoal / Not for sale (idle)
      if (plot.status === "Pending") return 0x475569; // Slate Gray (Pending Verification)
      if (plot.status === "Disputed") return 0x7f1d1d; // Dark Muted Maroon (Legal Dispute)
    }

    // Fallback standard real-time state color rule
    if (plot.status === "Disputed") return 0xef4444; // Red
    if (plot.status === "Pending") return 0xf59e0b;  // Amber
    if (isListed) return 0x22c55e;                   // Green
    return 0x3b82f6;                                 // Blue
  }

  updateMeshStyles() {
    this.plotMeshes.forEach((group) => {
      const plot = group.userData.plot;
      const mesh = group.userData.mesh;
      const lines = group.userData.edgeLines;

      const isOwner = this.currentUserOwnerId && plot.owner_id === this.currentUserOwnerId;
      const isListed = plot.status === 'Clear' && plot.active_ask !== null && plot.active_ask !== undefined;

      // Filter Visibility
      let isVisible = true;
      if (this.viewFilter === 'available' && !isListed) isVisible = false;
      if (this.viewFilter === 'my_plots' && !isOwner) isVisible = false;
      if (this.viewFilter === 'pending' && plot.status !== 'Pending') isVisible = false;
      if (this.viewFilter === 'disputed' && plot.status !== 'Disputed') isVisible = false;

      group.visible = isVisible;
      if (!isVisible) return;

      mesh.material.color.setHex(this.getPlotColor(plot));

      // Outline styling
      if (isOwner) {
        lines.material.color.setHex(0xffffff); // Bold White border for owned plots
        lines.material.linewidth = 3;
      } else if (this.currentUserRole === 'owner_seller') {
        lines.material.color.setHex(0x334155); // Faint borders for others in seller view
        lines.material.linewidth = 1;
      } else {
        lines.material.color.setHex(0x0f172a);
        lines.material.linewidth = 1;
      }
    });
  }

  initInteraction() {
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();
    this.hoveredMesh = null;
    this.hoveredMeshOrigColor = null;
    this.tooltipElement = document.getElementById('plot-tooltip');

    // Mouse move: Raycast for hovering effects, cursor change, and floating tooltip
    this.container.addEventListener('mousemove', (event) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObjects(this.scene.children, true);

      let foundGroup = null;
      if (intersects.length > 0) {
        let target = intersects[0].object;
        while (target.parent && target.parent !== this.scene && !target.userData.plot) {
          target = target.parent;
        }
        if (target.userData && target.userData.plot) {
          foundGroup = target;
        }
      }

      if (foundGroup) {
        this.container.style.cursor = 'pointer';
        const plot = foundGroup.userData.plot;
        const mesh = foundGroup.userData.mesh;

        // Highlight mesh on hover
        if (this.hoveredMesh !== mesh) {
          if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
            this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
          }
          this.hoveredMesh = mesh;
          this.hoveredMeshOrigColor = this.getPlotColor(plot);
          // Brighten mesh color slightly on hover
          const hoverColor = new THREE.Color(this.hoveredMeshOrigColor).offsetHSL(0, 0.05, 0.15);
          mesh.material.color.copy(hoverColor);
        }

        // Show floating tooltip
        if (this.tooltipElement) {
          const isAvailable = plot.status === 'Clear' && plot.active_ask !== null && plot.active_ask !== undefined;
          const statusColor = plot.status === 'Disputed' ? '#ef4444' : (plot.status === 'Pending' ? '#f59e0b' : (isAvailable ? '#22c55e' : '#3b82f6'));
          const availabilityBadge = isAvailable
            ? '<span class="tooltip-badge" style="background: rgba(34, 197, 94, 0.2); color: #4ade80;">Available for Sale</span>'
            : (plot.status === 'Clear' 
                ? '<span class="tooltip-badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">Not Listed</span>'
                : `<span class="tooltip-badge" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">${plot.status}</span>`);

          const priceHtml = plot.active_ask
            ? `₹${Number(plot.active_ask).toLocaleString()}`
            : (plot.best_bid ? `Best Bid: ₹${Number(plot.best_bid).toLocaleString()}` : '<span style="color:#94a3b8">No Active Ask</span>');

          this.tooltipElement.innerHTML = `
            <div class="tooltip-header">
              <span>${plot.plot_id}</span>
              ${availabilityBadge}
            </div>
            <div class="tooltip-row">
              <span>Address:</span>
              <strong style="max-width: 140px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${plot.street_address || 'Bengaluru Parcel'}</strong>
            </div>
            <div class="tooltip-row">
              <span>Area:</span>
              <span>${plot.area_sqft ? Math.round(plot.area_sqft).toLocaleString() + ' sq ft' : '--'}</span>
            </div>
            <div class="tooltip-row" style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(255,255,255,0.1);">
              <span style="font-weight: 600;">Price:</span>
              <strong style="color: ${isAvailable ? '#4ade80' : '#f8fafc'}; font-size: 0.9rem;">${priceHtml}</strong>
            </div>
          `;

          // Position tooltip relative to container, offset slightly from mouse
          const posX = event.clientX - rect.left + 15;
          const posY = event.clientY - rect.top + 15;
          this.tooltipElement.style.left = `${posX}px`;
          this.tooltipElement.style.top = `${posY}px`;
          this.tooltipElement.classList.remove('hidden');
        }
      } else {
        this.container.style.cursor = 'default';
        if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
          this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
          this.hoveredMesh = null;
          this.hoveredMeshOrigColor = null;
        }
        if (this.tooltipElement) {
          this.tooltipElement.classList.add('hidden');
        }
      }
    });

    this.container.addEventListener('mouseleave', () => {
      if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
        this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
        this.hoveredMesh = null;
        this.hoveredMeshOrigColor = null;
      }
      if (this.tooltipElement) {
        this.tooltipElement.classList.add('hidden');
      }
    });

    this.container.addEventListener('click', (event) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObjects(this.scene.children, true);

      if (intersects.length > 0) {
        let target = intersects[0].object;
        while (target.parent && target.parent !== this.scene && !target.userData.plot) {
          target = target.parent;
        }

        if (target.userData && target.userData.plot) {
          const plot = target.userData.plot;
          if (this.onPlotSelect) {
            this.onPlotSelect(plot);
          }
        }
      }
    });
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
}
